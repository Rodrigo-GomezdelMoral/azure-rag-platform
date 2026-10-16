import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient

from app.config import Settings

MANIFEST = Path(__file__).resolve().parent.parent / "data" / "manifest.json"
EU_REUSE = "Commission Decision 2011/833/EU: reuse permitted with acknowledgement of the source"
EUR_LEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri="
EC = "https://health.ec.europa.eu/system/files/"
MDCG_2020_1 = f"{EC}2020-09/md_mdcg_2020_1_guidance_clinic_eva_md_software_en_0.pdf"
Document = tuple[str, str, str, str]
DOCUMENTS: list[Document] = [
    ("eu-2024-1689-ai-act.pdf", "EU-2024-1689", "Regulation (EU) 2024/1689 (AI Act)", f"{EUR_LEX}OJ:L_202401689"),
    ("eu-2017-745-mdr.pdf", "EU-2017-745", "Regulation (EU) 2017/745 (MDR)", f"{EUR_LEX}CELEX:32017R0745"),
    ("mdcg-2019-11.pdf", "MDCG-2019-11", "MDCG 2019-11 Qualification of software", f"{EC}2025-06/mdcg_2019_11_en.pdf"),
    ("mdcg-2020-1.pdf", "MDCG-2020-1", "MDCG 2020-1 Clinical evaluation of software", MDCG_2020_1),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; azure-rag-platform corpus fetcher)", "Accept": "application/pdf,*/*"}


async def download(http: httpx.AsyncClient, url: str) -> bytes:
    for _ in range(18):
        response = await http.get(url)
        if response.status_code == 200 and response.content.startswith(b"%PDF"):
            return response.content
        await asyncio.sleep(10)  # EUR-Lex answers 202 with an empty body while it renders the PDF
    raise RuntimeError(f"{url} did not return a PDF within three minutes")


async def stored_digest(container: ContainerClient, name: str) -> str | None:
    try:
        properties = await container.get_blob_client(name).get_blob_properties()
    except ResourceNotFoundError:
        return None
    return properties.metadata.get("sha256")


async def ingest(container: ContainerClient, http: httpx.AsyncClient, doc: Document) -> dict[str, str | int]:
    name, regulation, title, url = doc
    content = await download(http, url)
    digest = hashlib.sha256(content).hexdigest()
    metadata = {"regulation": regulation, "language": "en", "source_url": url, "sha256": digest}
    if await stored_digest(container, name) != digest:
        await container.upload_blob(name, content, overwrite=True, metadata=metadata, content_type="application/pdf")
    retrieved = datetime.now(UTC).date().isoformat()
    row: dict[str, str | int] = {"name": name, "regulation": regulation, "title": title, "url": url, "sha256": digest}
    return row | {"bytes": len(content), "language": "en", "licence": EU_REUSE, "retrieved": retrieved}


async def main() -> None:
    settings = Settings()
    async with (
        httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=120) as http,
        DefaultAzureCredential() as credential,
        ContainerClient.from_container_url(settings.corpus_container_url, credential=credential) as container,
    ):
        manifest = [await ingest(container, http, doc) for doc in DOCUMENTS]
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(manifest)} documents in {settings.corpus_container_url}, manifest at {MANIFEST}")


if __name__ == "__main__":
    asyncio.run(main())
