"""REST API views. Every user-specific view filters by `owner=request.user` (ownership enforced server-side)."""
import logging

from django.contrib.auth import authenticate
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_engine import assistant, bug_analyzer, llm
from ai_engine.indexing import load_overview
from ai_engine.search import hybrid_search

from . import services
from .models import AnalysisHistory, FixSuggestion, Repository
from .permissions import IsOwner
from .serializers import (BugSerializer, FixRequestSerializer, FixSerializer, HistorySerializer, LoginSerializer,
                          QuestionSerializer, RegisterSerializer, RepositoryCreateSerializer, RepositorySerializer,
                          ReviewSerializer, SearchRequestSerializer, UserSerializer)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ helpers --
def error(message: str, code: str, http_status: int, **extra) -> Response:
    return Response({"detail": message, "code": code, **extra}, status=http_status)

def llm_failure(exc: llm.LLMError) -> Response:
    logger.error("LLM request failed: %s: %s", type(exc).__name__, exc)

    if isinstance(exc, llm.LLMNotConfigured):
        return error(str(exc), "llm_not_configured", status.HTTP_503_SERVICE_UNAVAILABLE)

    return error(str(exc), "llm_error", status.HTTP_502_BAD_GATEWAY)


def owned_repository(request, pk) -> Repository:
    return get_object_or_404(Repository, pk=pk, owner=request.user)


def analyzed_repository(request, pk):
    """Return (repo, None) or (None, error_response) when the repository has no search index yet."""
    repo = owned_repository(request, pk)
    if repo.analysis_status != Repository.Status.COMPLETED:
        return None, error("Analyze this repository first, then try again.", "not_analyzed", status.HTTP_409_CONFLICT)
    return repo, None


def retrieval_options():
    from django.conf import settings
    return {"model_name": settings.EMBEDDING_MODEL}


# --------------------------------------------------------------------- auth --
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(username=serializer.validated_data["username"], password=serializer.validated_data["password"])
        if user is None:
            return error("Incorrect username or password.", "invalid_credentials", status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()  # invalidates the token server-side
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok", "llm_configured": llm.is_configured()})


# --------------------------------------------------------------- repositories --
class RepositoryListCreateView(APIView):
    def get(self, request):
        repos = Repository.objects.filter(owner=request.user)
        return Response(RepositorySerializer(repos, many=True).data)

    def post(self, request):
        serializer = RepositoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            repo = services.import_repository(request.user, serializer.validated_data["url"])
        except services.RepositoryImportError as exc:
            return error(str(exc), type(exc).__name__, exc.status_code)
        return Response(RepositorySerializer(repo).data, status=status.HTTP_201_CREATED)


class RepositoryDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = RepositorySerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Repository.objects.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        services.delete_repository_files(instance)
        instance.delete()


class RepositoryAnalyzeView(APIView):
    def post(self, request, pk):
        repo = owned_repository(request, pk)
        if repo.analysis_status == Repository.Status.ANALYZING:
            return error("This repository is already being analyzed.", "already_running", status.HTTP_409_CONFLICT)
        try:
            services.run_analysis(repo)
        except Exception:
            logger.exception("Analysis failed for repository %s", repo.pk)
            repo.refresh_from_db()
            return error(repo.analysis_error or "Analysis failed.", "analysis_failed", status.HTTP_422_UNPROCESSABLE_ENTITY)
        repo.refresh_from_db()
        return Response(RepositorySerializer(repo).data)


class RepositoryOverviewView(APIView):
    def get(self, request, pk):
        repo, problem = analyzed_repository(request, pk)
        if problem:
            return problem
        overview = load_overview(services.index_dir(repo))
        if overview is None:
            return error("The analysis files are missing. Run the analysis again.", "not_analyzed", status.HTTP_409_CONFLICT)
        return Response(overview)


class RepositorySearchView(APIView):
    def post(self, request, pk):
        repo, problem = analyzed_repository(request, pk)
        if problem:
            return problem
        data = SearchRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = hybrid_search(services.index_dir(repo), data.validated_data["query"], data.validated_data["top_k"],
                               data.validated_data["mode"], **retrieval_options())
        return Response(result)


# ------------------------------------------------------------------ AI views --
class RepositoryAskView(APIView):
    throttle_scope = "llm"

    def post(self, request, pk):
        repo, problem = analyzed_repository(request, pk)
        if problem:
            return problem
        data = QuestionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            result = assistant.answer_question(data.validated_data["question"], services.index_dir(repo),
                                               data.validated_data["top_k"], **retrieval_options())
        except llm.LLMError as exc:
            return llm_failure(exc)
        record = AnalysisHistory.objects.create(
            owner=request.user, repository=repo, analysis_type=AnalysisHistory.Type.QUESTION,
            user_input=data.validated_data["question"], ai_response=result["answer"],
            file_references=result["references"], llm_model=result["model"])
        return Response({**result, "history_id": record.id})


class RepositoryInvestigateView(APIView):
    throttle_scope = "llm"

    def post(self, request, pk):
        repo, problem = analyzed_repository(request, pk)
        if problem:
            return problem
        data = BugSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            result = bug_analyzer.investigate_bug(data.validated_data["description"], services.index_dir(repo),
                                                  data.validated_data["top_k"], **retrieval_options())
        except llm.LLMError as exc:
            return llm_failure(exc)
        record = AnalysisHistory.objects.create(
            owner=request.user, repository=repo, analysis_type=AnalysisHistory.Type.BUG,
            user_input=data.validated_data["description"], ai_response=result["analysis"],
            file_references=result["references"], llm_model=result["model"])
        return Response({**result, "history_id": record.id})


class RepositorySuggestFixView(APIView):
    throttle_scope = "llm"

    def post(self, request, pk):
        repo, problem = analyzed_repository(request, pk)
        if problem:
            return problem
        data = FixRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        description = data.validated_data["description"]
        signals = bug_analyzer.extract_error_signals(description)
        try:
            search = bug_analyzer.retrieve_for_bug(description, services.index_dir(repo), signals, **retrieval_options())
            outcome = assistant.suggest_patch(description, search["results"], search["mode_used"])
        except llm.LLMError as exc:
            return llm_failure(exc)
        if outcome["proposal"] is None:
            return Response({"suggestion": None, "cannot_fix_reason": outcome["cannot_fix_reason"] or "The AI could not propose a safe change.",
                             "references": outcome["references"]}, status=status.HTTP_200_OK)
        proposal = outcome["proposal"]
        try:  # check the proposal against the real file BEFORE saving it
            services.validate_patch(services.source_dir(repo), proposal["file_path"], proposal["original_code"], proposal["proposed_code"])
        except services.PatchValidationError as exc:
            return error(f"The AI proposed a change that failed validation and was discarded: {exc}", "invalid_patch", status.HTTP_422_UNPROCESSABLE_ENTITY)
        fix = FixSuggestion.objects.create(
            owner=request.user, repository=repo, problem_description=description, target_file=proposal["file_path"].replace("\\", "/"),
            original_code=proposal["original_code"], proposed_code=proposal["proposed_code"],
            explanation=proposal["explanation"], llm_model=outcome.get("model", ""))
        return Response({"suggestion": FixSerializer(fix).data, "cannot_fix_reason": "", "references": outcome["references"]},
                        status=status.HTTP_201_CREATED)


# -------------------------------------------------------------------- fixes --
class FixListView(generics.ListAPIView):
    serializer_class = FixSerializer

    def get_queryset(self):
        qs = FixSuggestion.objects.filter(owner=self.request.user).select_related("repository")
        repo_id = self.request.query_params.get("repository")
        return qs.filter(repository_id=repo_id) if repo_id and repo_id.isdigit() else qs


class FixDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = FixSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return FixSuggestion.objects.filter(owner=self.request.user).select_related("repository")


class FixReviewView(APIView):
    def post(self, request, pk):
        fix = get_object_or_404(FixSuggestion, pk=pk, owner=request.user)
        data = ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if fix.applied_at:
            return error("This change was already applied and can no longer be reviewed.", "already_applied", status.HTTP_409_CONFLICT)
        fix.review_decision = data.validated_data["decision"]
        fix.reviewed_at = timezone.now()
        fix.save(update_fields=["review_decision", "reviewed_at"])
        return Response(FixSerializer(fix).data)


class FixApplyView(APIView):
    """Writes an APPROVED change to the local working copy only. Nothing is ever pushed to GitHub."""

    def post(self, request, pk):
        fix = get_object_or_404(FixSuggestion.objects.select_related("repository"), pk=pk, owner=request.user)
        if fix.review_decision != FixSuggestion.Decision.APPROVED:
            return error("Approve the change before applying it.", "not_approved", status.HTTP_409_CONFLICT)
        if fix.applied_at:
            return error("This change was already applied.", "already_applied", status.HTTP_409_CONFLICT)
        try:
            services.apply_patch(services.source_dir(fix.repository), fix.target_file, fix.original_code, fix.proposed_code)
        except services.PatchValidationError as exc:
            return error(f"The change can no longer be applied safely: {exc}", "invalid_patch", status.HTTP_422_UNPROCESSABLE_ENTITY)
        fix.applied_at = timezone.now()
        fix.save(update_fields=["applied_at"])
        repo = fix.repository
        repo.metadata = {**repo.metadata, "index_stale": True}  # search index no longer matches the edited file
        repo.save(update_fields=["metadata", "updated_at"])
        return Response(FixSerializer(fix).data)


# ------------------------------------------------------------------ history --
class HistoryListView(generics.ListAPIView):
    serializer_class = HistorySerializer

    def get_queryset(self):
        qs = AnalysisHistory.objects.filter(owner=self.request.user).select_related("repository")
        repo_id = self.request.query_params.get("repository")
        kind = self.request.query_params.get("type")
        if repo_id and repo_id.isdigit():
            qs = qs.filter(repository_id=repo_id)
        if kind in AnalysisHistory.Type.values:
            qs = qs.filter(analysis_type=kind)
        return qs


class HistoryDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = HistorySerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return AnalysisHistory.objects.filter(owner=self.request.user).select_related("repository")


class DashboardView(APIView):
    def get(self, request):
        repos = Repository.objects.filter(owner=request.user)
        history = AnalysisHistory.objects.filter(owner=request.user).select_related("repository")
        by_status = {row["analysis_status"]: row["n"] for row in repos.values("analysis_status").annotate(n=Count("id"))}
        return Response({
            "repository_count": repos.count(),
            "repositories_analyzed": by_status.get(Repository.Status.COMPLETED, 0),
            "analysis_count": history.count(),
            "fix_suggestion_count": FixSuggestion.objects.filter(owner=request.user).count(),
            "recent_analyses": HistorySerializer(history[:5], many=True).data,
        })
