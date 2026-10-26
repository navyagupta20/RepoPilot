import uuid

from django.conf import settings
from django.db import models


def new_workspace_ref() -> str:
    """Random folder name for a repository's files - never derived from user input."""
    return uuid.uuid4().hex


class Repository(models.Model):
    class Status(models.TextChoices):
        NOT_ANALYZED = "not_analyzed", "Not analyzed"
        ANALYZING = "analyzing", "Analyzing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="repositories")
    name = models.CharField(max_length=200)  # "owner/repo"
    github_url = models.URLField(max_length=300)
    workspace_ref = models.CharField(max_length=64, unique=True, default=new_workspace_ref)  # relative, never an absolute path
    metadata = models.JSONField(default=dict, blank=True)  # description, stars, languages, file_count, semantic status ...
    analysis_status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_ANALYZED)
    analysis_error = models.TextField(blank=True)
    last_analyzed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["owner", "github_url"], name="unique_repo_per_owner")]

    def __str__(self):
        return f"{self.name} ({self.owner})"


class AnalysisHistory(models.Model):
    class Type(models.TextChoices):
        QUESTION = "question", "Code question"
        BUG = "bug", "Bug investigation"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analyses")
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="analyses")
    analysis_type = models.CharField(max_length=20, choices=Type.choices)
    user_input = models.TextField()  # the question or bug description
    ai_response = models.TextField()
    file_references = models.JSONField(default=list, blank=True)
    llm_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "analysis history"

    def __str__(self):
        return f"{self.get_analysis_type_display()} on {self.repository.name}"


class FixSuggestion(models.Model):
    class Decision(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fix_suggestions")
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="fix_suggestions")
    problem_description = models.TextField()
    target_file = models.CharField(max_length=500)
    original_code = models.TextField()
    proposed_code = models.TextField()
    explanation = models.TextField()
    review_decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)  # set only after an approved change is written to the LOCAL working copy
    llm_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Fix for {self.target_file} ({self.review_decision})"
