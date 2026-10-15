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
DOCUMENTS = [
    {
        "name": "eu-2024-1689-ai-act.pdf",
        "regulation": "EU-2024-1689",
        "title": "Regulation (EU) 2024/1689 (Artificial Intelligence Act), OJ L 12.7.2024",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689",
    },
    {
        "name": "eu-2017-745-mdr.pdf",
        "regulation": "EU-2017-745",
        "title": "Regulation (EU) 2017/745 (Medical Device Regulation), OJ L 117 5.5.2017",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32017R0745",
    },
    {
        "name": "mdcg-2019-11.pdf",
        "regulation": "MDCG-2019-11",
        "title": "MDCG 2019-11 rev.1 Qualification and classification of software (MDR and IVDR)",
        "url": "https://health.ec.europa.eu/system/files/2025-06/mdcg_2019_11_en.pdf",
    },
    {
        "name": "mdcg-2020-1.pdf",
        "regulation": "MDCG-2020-1",
        "title": "MDCG 2020-1 Clinical evaluation (MDR) and performance evaluation (IVDR) of medical device software",
        "url": "https://health.ec.europa.eu/system/files/2020-09/md_mdcg_2020_1_guidance_clinic_eva_md_software_en_0.pdf",
    },
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


async def ingest(container: ContainerClient, http: httpx.AsyncClient, doc: dict[str, str]) -> dict[str, str | int]:
    content = await download(http, doc["url"])
    digest = hashlib.sha256(content).hexdigest()
    metadata = {"regulation": doc["regulation"], "language": "en", "source_url": doc["url"], "sha256": digest}
    if await stored_digest(container, doc["name"]) != digest:
        await container.upload_blob(
            doc["name"], content, overwrite=True, metadata=metadata, content_type="application/pdf"
        )
    retrieved = datetime.now(UTC).date().isoformat()
    return {
        **doc,
        "sha256": digest,
        "bytes": len(content),
        "language": "en",
        "licence": EU_REUSE,
        "retrieved": retrieved,
    }


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
