from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from . import services
from .models import AnalysisHistory, FixSuggestion, Repository

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class RegisterSerializer(serializers.Serializer):
    username = serializers.RegexField(r"^[\w.@+-]+$", min_length=3, max_length=30,
                                      error_messages={"invalid": "Use letters, numbers and . @ + - _ only."})
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs["username"], email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], candidate)
        except Exception as exc:  # DjangoValidationError -> DRF error list
            raise serializers.ValidationError({"password": list(getattr(exc, "messages", [str(exc)]))})
        return attrs

    def create(self, validated):
        return User.objects.create_user(username=validated["username"], email=validated.get("email", ""), password=validated["password"])


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RepositorySerializer(serializers.ModelSerializer):
    primary_language = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = ["id", "name", "github_url", "metadata", "primary_language", "file_count", "analysis_status",
                  "analysis_error", "last_analyzed_at", "created_at", "updated_at"]  # workspace_ref is deliberately NOT exposed
        read_only_fields = fields

    def get_primary_language(self, obj):
        return obj.metadata.get("primary_language", "")

    def get_file_count(self, obj):
        return obj.metadata.get("file_count", 0)


class RepositoryCreateSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=300)

    def validate_url(self, value):
        try:
            services.parse_github_url(value)
        except services.InvalidRepositoryURL as exc:
            raise serializers.ValidationError(str(exc))
        return value


class SearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)
    mode = serializers.ChoiceField(choices=["hybrid", "keyword", "semantic"], default="hybrid")
    top_k = serializers.IntegerField(min_value=1, max_value=20, default=8)


class QuestionSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    top_k = serializers.IntegerField(min_value=1, max_value=15, default=8)


class BugSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=6000)
    top_k = serializers.IntegerField(min_value=1, max_value=15, default=8)


class FixRequestSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=4000)


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])


class HistorySerializer(serializers.ModelSerializer):
    repository_name = serializers.CharField(source="repository.name", read_only=True)
    analysis_type_label = serializers.CharField(source="get_analysis_type_display", read_only=True)

    class Meta:
        model = AnalysisHistory
        fields = ["id", "repository", "repository_name", "analysis_type", "analysis_type_label", "user_input",
                  "ai_response", "file_references", "llm_model", "created_at"]
        read_only_fields = fields


class FixSerializer(serializers.ModelSerializer):
    repository_name = serializers.CharField(source="repository.name", read_only=True)
    diff = serializers.SerializerMethodField()
    verified = serializers.SerializerMethodField()

    class Meta:
        model = FixSuggestion
        fields = ["id", "repository", "repository_name", "problem_description", "target_file", "original_code",
                  "proposed_code", "explanation", "diff", "review_decision", "reviewed_at", "applied_at",
                  "verified", "llm_model", "created_at"]
        read_only_fields = fields

    def get_diff(self, obj):
        return services.make_diff(obj.original_code, obj.proposed_code, obj.target_file)

    def get_verified(self, obj):
        return False  # RepoPilot never runs tests, so a suggestion is never "verified"
