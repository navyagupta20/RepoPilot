from django.contrib import admin

from .models import AnalysisHistory, FixSuggestion, Repository

admin.site.register(Repository)
admin.site.register(AnalysisHistory)
admin.site.register(FixSuggestion)
