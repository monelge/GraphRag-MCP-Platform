from .base import BaseNode, NodeResult
from .planner import PlannerNode
from .retriever import RetrieverNode
from .explainer import ExplainerNode
from .editor import EditorNode
from .verifier import VerifierNode
from .reviewer import ReviewerNode
from .summarizer import SummarizerNode

NODE_REGISTRY = {
    "planner": PlannerNode,
    "retriever": RetrieverNode,
    "explainer": ExplainerNode,
    "editor": EditorNode,
    "verifier": VerifierNode,
    "reviewer": ReviewerNode,
    "summarizer": SummarizerNode,
}

DEFAULT_PIPELINE = ["planner", "retriever", "explainer", "editor", "verifier", "reviewer", "summarizer"]
