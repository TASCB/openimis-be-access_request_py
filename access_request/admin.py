from django.contrib import admin

from access_request.models import AccessProfile, AccessRequest

admin.site.register(AccessProfile)
admin.site.register(AccessRequest)
