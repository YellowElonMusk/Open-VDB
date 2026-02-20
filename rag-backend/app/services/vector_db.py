"""Vector database service with multi-tenant isolation using Milvus"""

import uuid
from typing import List, Dict, Any, Optional, Tuple
from pymilvus import (
    connections, Collection, CollectionSchema, FieldSchema, DataType,
    utility, IndexType, MetricType
)
import structlog
from app.config import settings

logger = structlog.get_logger(__name__)


class VectorDBService:
    """Multi-tenant vector database service with isolated collections per OEM"""

    def __init__(self):
        self.connected = False
        self.collections: Dict[str, Collection] = {}

    async def connect(self):
        """Connect to Milvus server"""
        try:
            connections.connect(
                alias="default",
                host=settings.milvus_host,
                port=settings.milvus_port,
                user=settings.milvus_user,
                password=settings.milvus_password,
                secure=settings.milvus_secure,
            )
            self.connected = True
            logger.info("Connected to Milvus", host=settings.milvus_host)
        except Exception as e:
            logger.error("Failed to connect to Milvus", error=str(e))
            raise

    async def disconnect(self):
        """Disconnect from Milvus"""
        try:
            connections.disconnect("default")
            self.connected = False
            logger.info("Disconnected from Milvus")
        except Exception as e:
            logger.error("Failed to disconnect from Milvus", error=str(e))

    def _get_collection_schema(self) -> CollectionSchema:
        """Define the schema for document chunks with vectors"""
        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                max_length=36,
                is_primary=True,
                description="Chunk UUID"
            ),
            FieldSchema(
                name="document_id",
                dtype=DataType.VARCHAR,
                max_length=36,
                description="Document UUID"
            ),
            FieldSchema(
                name="chunk_index",
                dtype=DataType.INT64,
                description="Chunk position in document"
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                description="Text content of chunk"
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=settings.embeddings_dimension,
                description="Embedding vector"
            ),
            FieldSchema(
                name="page_number",
                dtype=DataType.INT64,
                description="Page number (0 if N/A)"
            ),
            FieldSchema(
                name="equipment_model",
                dtype=DataType.VARCHAR,
                max_length=255,
                description="Equipment model tag"
            ),
            FieldSchema(
                name="document_title",
                dtype=DataType.VARCHAR,
                max_length=512,
                description="Document title"
            ),
            FieldSchema(
                name="section_title",
                dtype=DataType.VARCHAR,
                max_length=512,
                description="Section title"
            ),
        ]

        return CollectionSchema(
            fields=fields,
            description="Document chunks with embeddings for RAG",
            enable_dynamic_field=True
        )

    async def create_oem_collection(self, oem_id: str, collection_name: str) -> bool:
        """
        Create an isolated collection for an OEM

        Args:
            oem_id: OEM unique identifier
            collection_name: Unique collection name for this OEM

        Returns:
            True if created successfully
        """
        try:
            # Check if collection already exists
            if utility.has_collection(collection_name):
                logger.warning(
                    "Collection already exists",
                    collection_name=collection_name,
                    oem_id=oem_id
                )
                return False

            # Create collection
            schema = self._get_collection_schema()
            collection = Collection(
                name=collection_name,
                schema=schema,
                using="default"
            )

            # Create index on embedding field for fast similarity search
            index_params = {
                "index_type": "IVF_FLAT",
                "metric_type": "L2",  # Euclidean distance
                "params": {"nlist": 1024}
            }
            collection.create_index(
                field_name="embedding",
                index_params=index_params
            )

            # Create index on document_id for filtering
            collection.create_index(
                field_name="document_id",
                index_params={"index_type": "STL_SORT"}
            )

            # Create index on equipment_model for filtering
            collection.create_index(
                field_name="equipment_model",
                index_params={"index_type": "STL_SORT"}
            )

            # Load collection into memory for fast queries
            collection.load()

            self.collections[collection_name] = collection

            logger.info(
                "Created OEM collection",
                oem_id=oem_id,
                collection_name=collection_name
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to create collection",
                oem_id=oem_id,
                collection_name=collection_name,
                error=str(e)
            )
            raise

    async def delete_oem_collection(self, collection_name: str) -> bool:
        """
        Delete an OEM's collection (hard delete)

        Args:
            collection_name: Collection to delete

        Returns:
            True if deleted successfully
        """
        try:
            if not utility.has_collection(collection_name):
                logger.warning("Collection does not exist", collection_name=collection_name)
                return False

            # Remove from cache
            if collection_name in self.collections:
                del self.collections[collection_name]

            # Drop collection
            utility.drop_collection(collection_name)

            logger.info("Deleted OEM collection", collection_name=collection_name)
            return True

        except Exception as e:
            logger.error(
                "Failed to delete collection",
                collection_name=collection_name,
                error=str(e)
            )
            raise

    def _get_collection(self, collection_name: str) -> Collection:
        """Get or load a collection"""
        if collection_name not in self.collections:
            if not utility.has_collection(collection_name):
                raise ValueError(f"Collection {collection_name} does not exist")

            collection = Collection(collection_name)
            collection.load()
            self.collections[collection_name] = collection

        return self.collections[collection_name]

    async def insert_chunks(
        self,
        collection_name: str,
        chunks: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Insert document chunks with embeddings into OEM's collection

        Args:
            collection_name: OEM's collection name
            chunks: List of chunk dictionaries with embeddings

        Returns:
            List of inserted chunk IDs
        """
        try:
            collection = self._get_collection(collection_name)

            ids = []
            document_ids = []
            chunk_indices = []
            contents = []
            embeddings = []
            page_numbers = []
            equipment_models = []
            document_titles = []
            section_titles = []

            for chunk in chunks:
                ids.append(chunk["id"])
                document_ids.append(chunk["document_id"])
                chunk_indices.append(chunk["chunk_index"])
                contents.append(chunk["content"])
                embeddings.append(chunk["embedding"])
                page_numbers.append(chunk.get("page_number", 0))
                equipment_models.append(chunk.get("equipment_model", ""))
                document_titles.append(chunk.get("document_title", ""))
                section_titles.append(chunk.get("section_title", ""))

            data = [
                ids,
                document_ids,
                chunk_indices,
                contents,
                embeddings,
                page_numbers,
                equipment_models,
                document_titles,
                section_titles,
            ]

            collection.insert(data)
            collection.flush()

            logger.info(
                "Inserted chunks",
                collection_name=collection_name,
                count=len(chunks)
            )

            return ids

        except Exception as e:
            logger.error(
                "Failed to insert chunks",
                collection_name=collection_name,
                error=str(e)
            )
            raise

    async def search_similar(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int = 5,
        equipment_model: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks in OEM's collection

        Args:
            collection_name: OEM's collection name
            query_embedding: Query vector
            top_k: Number of results to return
            equipment_model: Filter by equipment model
            document_ids: Filter by specific documents

        Returns:
            List of similar chunks with scores
        """
        try:
            collection = self._get_collection(collection_name)

            # Build filter expression
            filter_expr = None
            if equipment_model and document_ids:
                doc_ids_str = ",".join([f"'{doc_id}'" for doc_id in document_ids])
                filter_expr = f"equipment_model == '{equipment_model}' && document_id in [{doc_ids_str}]"
            elif equipment_model:
                filter_expr = f"equipment_model == '{equipment_model}'"
            elif document_ids:
                doc_ids_str = ",".join([f"'{doc_id}'" for doc_id in document_ids])
                filter_expr = f"document_id in [{doc_ids_str}]"

            search_params = {
                "metric_type": "L2",
                "params": {"nprobe": 10}
            }

            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filter_expr,
                output_fields=[
                    "id", "document_id", "chunk_index", "content",
                    "page_number", "equipment_model", "document_title", "section_title"
                ]
            )

            formatted_results = []
            for hits in results:
                for hit in hits:
                    formatted_results.append({
                        "id": hit.entity.get("id"),
                        "document_id": hit.entity.get("document_id"),
                        "chunk_index": hit.entity.get("chunk_index"),
                        "content": hit.entity.get("content"),
                        "page_number": hit.entity.get("page_number"),
                        "equipment_model": hit.entity.get("equipment_model"),
                        "document_title": hit.entity.get("document_title"),
                        "section_title": hit.entity.get("section_title"),
                        "distance": hit.distance,
                        "score": 1.0 / (1.0 + hit.distance)  # Convert distance to similarity score
                    })

            logger.info(
                "Performed similarity search",
                collection_name=collection_name,
                top_k=top_k,
                results_count=len(formatted_results)
            )

            return formatted_results

        except Exception as e:
            logger.error(
                "Failed to search",
                collection_name=collection_name,
                error=str(e)
            )
            raise

    async def delete_document_chunks(
        self,
        collection_name: str,
        document_id: str
    ) -> int:
        """
        Delete all chunks for a specific document

        Args:
            collection_name: OEM's collection name
            document_id: Document UUID

        Returns:
            Number of chunks deleted
        """
        try:
            collection = self._get_collection(collection_name)

            expr = f"document_id == '{document_id}'"
            collection.delete(expr)
            collection.flush()

            logger.info(
                "Deleted document chunks",
                collection_name=collection_name,
                document_id=document_id
            )

            return 1  # Milvus doesn't return delete count

        except Exception as e:
            logger.error(
                "Failed to delete chunks",
                collection_name=collection_name,
                document_id=document_id,
                error=str(e)
            )
            raise

    async def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """
        Get statistics for an OEM's collection

        Args:
            collection_name: OEM's collection name

        Returns:
            Collection statistics
        """
        try:
            collection = self._get_collection(collection_name)

            stats = collection.get_stats()
            num_entities = collection.num_entities

            return {
                "collection_name": collection_name,
                "num_entities": num_entities,
                "raw_stats": stats
            }

        except Exception as e:
            logger.error(
                "Failed to get stats",
                collection_name=collection_name,
                error=str(e)
            )
            raise


# Global instance
vector_db = VectorDBService()
