from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Relationship


class RelationshipStore(ABC):
    @abstractmethod
    def upsert(self, relationship: Relationship) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_for_entity(self, entity_type: str, entity_id: str) -> list[Relationship]:
        raise NotImplementedError


class InMemoryRelationshipStore(RelationshipStore):
    def __init__(self) -> None:
        self._relationships: dict[str, Relationship] = {}

    def upsert(self, relationship: Relationship) -> None:
        self._relationships[relationship.relationship_id] = relationship

    def get_for_entity(self, entity_type: str, entity_id: str) -> list[Relationship]:
        return [
            rel for rel in self._relationships.values()
            if (rel.source.type, rel.source.id) == (entity_type, entity_id)
            or (rel.target.type, rel.target.id) == (entity_type, entity_id)
        ]
