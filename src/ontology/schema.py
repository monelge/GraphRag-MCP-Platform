"""
GraphRag ontology şeması — repo bilgi grafiği için node ve edge tipleri.
v2.md Repo Ontology bölümüne dayanır.
"""

from enum import Enum


class NodeType(str, Enum):
    REPOSITORY = "Repository"
    MODULE = "Module"
    PACKAGE = "Package"
    FILE = "File"
    CLASS = "Class"
    INTERFACE = "Interface"
    FUNCTION = "Function"
    METHOD = "Method"
    ENDPOINT = "Endpoint"
    ENTITY = "Entity"
    DTO = "DTO"
    CONFIG = "Config"
    MIGRATION = "Migration"
    UI_COMPONENT = "UIComponent"
    BUSINESS_RULE = "BusinessRule"
    DECISION = "Decision"
    OWNER = "Owner"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    OWNS = "OWNS"
    CALLS = "CALLS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"
    EXPOSES_ENDPOINT = "EXPOSES_ENDPOINT"
    USES_CONFIG = "USES_CONFIG"
    MUTATES_ENTITY = "MUTATES_ENTITY"
    READS_ENTITY = "READS_ENTITY"
    RELATES_TO_RULE = "RELATES_TO_RULE"
    AFFECTS_MODULE = "AFFECTS_MODULE"
    SUPERSEDES_DECISION = "SUPERSEDES_DECISION"
