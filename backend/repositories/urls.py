from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    # authentication
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    # dashboard
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    # repositories
    path("repositories/", views.RepositoryListCreateView.as_view(), name="repository-list"),
    path("repositories/<int:pk>/", views.RepositoryDetailView.as_view(), name="repository-detail"),
    path("repositories/<int:pk>/analyze/", views.RepositoryAnalyzeView.as_view(), name="repository-analyze"),
    path("repositories/<int:pk>/overview/", views.RepositoryOverviewView.as_view(), name="repository-overview"),
    path("repositories/<int:pk>/search/", views.RepositorySearchView.as_view(), name="repository-search"),
    path("repositories/<int:pk>/ask/", views.RepositoryAskView.as_view(), name="repository-ask"),
    path("repositories/<int:pk>/investigate/", views.RepositoryInvestigateView.as_view(), name="repository-investigate"),
    path("repositories/<int:pk>/suggest-fix/", views.RepositorySuggestFixView.as_view(), name="repository-suggest-fix"),
    # fix suggestions
    path("fixes/", views.FixListView.as_view(), name="fix-list"),
    path("fixes/<int:pk>/", views.FixDetailView.as_view(), name="fix-detail"),
    path("fixes/<int:pk>/review/", views.FixReviewView.as_view(), name="fix-review"),
    path("fixes/<int:pk>/apply/", views.FixApplyView.as_view(), name="fix-apply"),
    # analysis history
    path("history/", views.HistoryListView.as_view(), name="history-list"),
    path("history/<int:pk>/", views.HistoryDetailView.as_view(), name="history-detail"),
]
