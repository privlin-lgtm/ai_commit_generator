"""AI-powered Git commit message generation."""

from ai_commit_generator.application import (
    GenerateCommitMessage,
)
from ai_commit_generator.commit_analyzer import ConventionalCommitAnalyzer
from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.config import ProviderName, Settings, load_settings
from ai_commit_generator.git_diff import GitDiffAnalyzer, GitOutputLimitError
from ai_commit_generator.git_hooks import GitHookInstaller, PrepareCommitMessageHook
from ai_commit_generator.llm_client import (
    AnthropicProvider,
    AzureOpenAIProvider,
    BaseLLMProvider,
    OllamaProvider,
    OpenAIProvider,
    RetryingLLMProvider,
)
from ai_commit_generator.models import (
    CommitMessage,
    CommitStyle,
    ConventionalCommitType,
    GenerateCommitRequest,
    GitDiffAnalysis,
)
from ai_commit_generator.response_validator import (
    CommitResponseLimitError,
    ConventionalCommitResponseValidator,
    StyleAwareCommitResponseValidator,
)

__all__ = [
    "AnthropicProvider",
    "AzureOpenAIProvider",
    "BaseLLMProvider",
    "CommitMessage",
    "CommitMessageGenerator",
    "CommitResponseLimitError",
    "CommitStyle",
    "ConventionalCommitAnalyzer",
    "ConventionalCommitResponseValidator",
    "ConventionalCommitType",
    "GenerateCommitMessage",
    "GenerateCommitRequest",
    "GitDiffAnalysis",
    "GitDiffAnalyzer",
    "GitHookInstaller",
    "GitOutputLimitError",
    "OllamaProvider",
    "OpenAIProvider",
    "PrepareCommitMessageHook",
    "ProviderName",
    "RetryingLLMProvider",
    "Settings",
    "StyleAwareCommitResponseValidator",
    "load_settings",
]
__version__ = "0.5.0"
