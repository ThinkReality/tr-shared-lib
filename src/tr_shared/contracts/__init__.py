"""Cross-domain platform contracts: the Feature taxonomy spine, entity types,
shared enums, and the term glossary. Single source of truth for all services."""

from tr_shared.contracts.entity_types import EntityType
from tr_shared.contracts.enums import Channel, Priority
from tr_shared.contracts.glossary import GLOSSARY, Term
from tr_shared.contracts.taxonomy import Feature

__all__ = ["GLOSSARY", "Channel", "EntityType", "Feature", "Priority", "Term"]
