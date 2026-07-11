"""Admin, auth, and access-control models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import AdminUsers as AdminUser
from app.backend_db._generated_models import AuthGroup as AuthGroup
from app.backend_db._generated_models import AuthPermission as AuthPermission
from app.backend_db._generated_models import DjangoContentType as DjangoContentType
from app.backend_db._generated_models import TokenBlacklistBlacklistedtoken as BlacklistedToken
from app.backend_db._generated_models import TokenBlacklistOutstandingtoken as OutstandingToken
from app.backend_db._generated_models import UsersGroups as UserGroup
from app.backend_db._generated_models import UsersUserPermissions as UserPermission

__all__ = [
    "AdminUser",
    "AuthGroup",
    "AuthPermission",
    "DjangoContentType",
    "UserGroup",
    "UserPermission",
    "OutstandingToken",
    "BlacklistedToken",
]
