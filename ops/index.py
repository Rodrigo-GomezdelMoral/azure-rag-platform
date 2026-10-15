import argparse
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes import models as m

from app.config import Settings

DIMENSIONS = 1536
ORIGINALS = "preserveOriginals"
SECTIONS = "/document/sections/*"
CHUNKS = f"{SECTIONS}/chunks/*"
H1, H2, H3 = (f"$({SECTIONS}/sections/h{level})" for level in (1, 2, 3))
REGULATION = "$(/document/regulation)"
CITATION_LABEL = f'={H2}!="" ? {H2} + ({H3}!="" ? " > " + {H3} : "") : ({H1}!="" ? {H1} : {REGULATION})'
ARTICLE = f'={H3}!="" ? {H3} : ({H2}!="" ? {H2} : ({H1}!="" ? {H1} : {REGULATION}))'
FACET: dict[str, Any] = {"filterable": True, "facetable": True, "searchable": False}
TEXT_FIELDS: dict[str, dict[str, Any]] = {
    "chunk_id": {"key": True, "analyzer_name": "keyword"},
    "content": {"analyzer_name": "en.microsoft"},
    "citation_label": {},
}
SIMPLE_FIELDS: dict[str, dict[str, Any]] = {
    "parent_id": {"filterable": True},
    "regulation": FACET,
    "article": FACET,
    "language": FACET,
    "source_url": {},
}
PROJECTION = {"content": CHUNKS, "content_vector": f"{CHUNKS}/vector"}
PROJECTION |= {name: f"{SECTIONS}/cite/{name}" for name in ("citation_label", "article")}
PROJECTION |= {name: f"/document/{name}" for name in ("regulation", "language", "source_url")}
Input, Output = m.InputFieldMappingEntry, m.OutputFieldMappingEntry
EMBED: dict[str, Any] = {"name": "embed", "context": CHUNKS, "dimensions": DIMENSIONS}
EMBED |= {"inputs": [Input(name="text", source=CHUNKS)], "outputs": [Output(name="embedding", target_name="vector")]}


def foundry_origin(settings: Settings) -> str:
    parsed = urlparse(settings.foundry_project_endpoint)
    return f"{parsed.scheme}://{parsed.hostname}"


def fields_definition(compressed: bool) -> list[m.SearchField]:
    vector = m.SearchField(
        name="content_vector",
        type="Collection(Edm.Single)",
        vector_search_dimensions=DIMENSIONS,
        vector_search_profile_name="regulations-vector",
        stored=not compressed,
        hidden=True,
    )
    text = [m.SearchableField(name=name, type="Edm.String", **attributes) for name, attributes in TEXT_FIELDS.items()]
    simple = [m.SimpleField(name=name, type="Edm.String", **attributes) for name, attributes in SIMPLE_FIELDS.items()]
    return [*text, *simple, vector]


def vector_search_definition(settings: Settings, compressed: bool) -> m.VectorSearch:
    rescoring = m.RescoringOptions(enable_rescoring=True, default_oversampling=4, rescore_storage_method=ORIGINALS)
    quantized = m.ScalarQuantizationParameters(quantized_data_type="int8")
    compression = m.ScalarQuantizationCompression(
        compression_name="int8", parameters=quantized, rescoring_options=rescoring
    )
    origin, model = foundry_origin(settings), settings.embedding_deployment
    embeddings = m.AzureOpenAIVectorizerParameters(resource_url=origin, deployment_name=model, model_name=model)
    profile = m.VectorSearchProfile(
        name="regulations-vector", algorithm_configuration_name="hnsw", vectorizer_name="shared-embeddings"
    )
    profile.compression_name = "int8" if compressed else None
    return m.VectorSearch(
        algorithms=[m.HnswAlgorithmConfiguration(name="hnsw")],
        compressions=[compression] if compressed else [],
        vectorizers=[m.AzureOpenAIVectorizer(vectorizer_name="shared-embeddings", parameters=embeddings)],
        profiles=[profile],
    )


def index_definition(settings: Settings, name: str, compressed: bool) -> m.SearchIndex:
    fields = m.SemanticPrioritizedFields(
        content_fields=[m.SemanticField(field_name="content")],
        keywords_fields=[m.SemanticField(field_name="citation_label")],
    )
    semantic = m.SemanticConfiguration(name=settings.semantic_configuration, prioritized_fields=fields)
    return m.SearchIndex(
        name=name,
        fields=fields_definition(compressed),
        vector_search=vector_search_definition(settings, compressed),
        semantic_search=m.SemanticSearch(default_configuration_name=semantic.name, configurations=[semantic]),
    )


def skills_definition(settings: Settings) -> list[m.SearchIndexerSkill]:
    origin, model = foundry_origin(settings), settings.embedding_deployment
    layout = m.DocumentIntelligenceLayoutSkill(
        name="layout",
        context="/document",
        output_mode="oneToMany",
        markdown_header_depth="h3",
        inputs=[Input(name="file_data", source="/document/file_data")],
        outputs=[Output(name="markdown_document", target_name="sections")],
    )
    split = m.SplitSkill(
        name="split",
        context=SECTIONS,
        text_split_mode="pages",
        maximum_page_length=2000,
        page_overlap_length=200,
        inputs=[Input(name="text", source=f"{SECTIONS}/content")],
        outputs=[Output(name="textItems", target_name="chunks")],
    )
    cite = m.ShaperSkill(
        name="cite",
        context=SECTIONS,
        inputs=[Input(name="citation_label", source=CITATION_LABEL), Input(name="article", source=ARTICLE)],
        outputs=[Output(name="output", target_name="cite")],
    )
    embed = m.AzureOpenAIEmbeddingSkill(resource_url=origin, deployment_name=model, model_name=model, **EMBED)
    return [layout, cite, split, embed]


def skillset_definition(settings: Settings, name: str, index_name: str) -> m.SearchIndexerSkillset:
    selector = m.SearchIndexerIndexProjectionSelector(
        target_index_name=index_name,
        parent_key_field_name="parent_id",
        source_context=CHUNKS,
        mappings=[Input(name=field, source=source) for field, source in PROJECTION.items()],
    )
    parameters = m.SearchIndexerIndexProjectionsParameters(projection_mode="skipIndexingParentDocuments")
    return m.SearchIndexerSkillset(
        name=name,
        skills=skills_definition(settings),
        cognitive_services_account=m.AIServicesAccountIdentity(subdomain_url=foundry_origin(settings)),
        index_projection=m.SearchIndexerIndexProjection(selectors=[selector], parameters=parameters),
    )


def data_source_definition(settings: Settings) -> m.SearchIndexerDataSourceConnection:
    soft = m.SoftDeleteColumnDeletionDetectionPolicy(
        soft_delete_column_name="isDeleted", soft_delete_marker_value="true"
    )
    return m.SearchIndexerDataSourceConnection(
        name="corpus",
        type="azureblob",
        connection_string=f"ResourceId={settings.storage_account_resource_id};",
        container=m.SearchIndexerDataContainer(name="corpus"),
        data_deletion_detection_policy=soft,
    )


def indexer_definition(index_name: str) -> m.SearchIndexer:
    configuration = m.IndexingParametersConfiguration(
        data_to_extract="storageMetadata", parsing_mode="default", allow_skillset_to_read_file_data=True
    )
    return m.SearchIndexer(
        name=f"{index_name}-indexer",
        data_source_name="corpus",
        skillset_name=f"{index_name}-skillset",
        target_index_name=index_name,
        schedule=m.IndexingSchedule(interval=timedelta(days=1)),
        parameters=m.IndexingParameters(batch_size=1, configuration=configuration),
    )


def run_and_wait(indexers: SearchIndexerClient, name: str) -> str:
    try:
        indexers.run_indexer(name)
    except HttpResponseError as error:
        if error.status_code != 409:
            raise
    while True:
        time.sleep(30)
        last = indexers.get_indexer_status(name).last_result
        if last is not None and last.status != "inProgress":
            problems = [
                last.error_message,
                *(e.error_message for e in last.errors),
                *(w.message for w in last.warnings),
            ]
            counts = f"{last.item_count} documents, {last.failed_item_count} failed"
            return f"{last.status}: {counts}, {[p[:120] for p in problems if p]}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update index, skillset, data source and indexer, then run it"
    )
    parser.add_argument(
        "--uncompressed", action="store_true", help="build a twin index without quantisation to measure it"
    )
    args = parser.parse_args()
    settings, credential = Settings(), DefaultAzureCredential()
    index_name = settings.search_index + ("-uncompressed" if args.uncompressed else "")
    indexes, indexers = (
        SearchIndexClient(settings.search_endpoint, credential),
        SearchIndexerClient(settings.search_endpoint, credential),
    )
    indexes.create_or_update_index(index_definition(settings, index_name, compressed=not args.uncompressed))
    indexers.create_or_update_data_source_connection(data_source_definition(settings))
    indexers.create_or_update_skillset(skillset_definition(settings, f"{index_name}-skillset", index_name))
    indexer = indexers.create_or_update_indexer(indexer_definition(index_name))
    print(run_and_wait(indexers, indexer.name))
    stats = indexes.get_index_statistics(index_name)
    sizes = f"{stats.storage_size:,} B storage, {stats.vector_index_size:,} B vector index"
    print(f"{index_name}: {stats.document_count} chunks, {sizes}")


if __name__ == "__main__":
    main()
