"""Validation classes for Access Request entities (openIMIS core validation mixins)."""
from core.validation import BaseModelValidation, UniqueCodeValidationMixin, ObjectExistsValidationMixin
from core.validation.stringFieldValidationMixin import StringFieldValidationMixin

from access_request.models import AccessProfile, AccessRequest


class AccessProfileValidation(BaseModelValidation, UniqueCodeValidationMixin,
                              ObjectExistsValidationMixin, StringFieldValidationMixin):
    OBJECT_TYPE = AccessProfile

    @classmethod
    def validate_create(cls, user, **data):
        code = data.get('code', None)
        cls.validate_empty_string(code)
        cls.validate_unique_code_name(code)

    @classmethod
    def validate_update(cls, user, **data):
        id_ = data.get('id', None)
        cls.validate_object_exists(id_)
        code = data.get('code', None)
        if code:
            cls.validate_unique_code_name(code, id_)


class AccessRequestValidation(BaseModelValidation, ObjectExistsValidationMixin):
    OBJECT_TYPE = AccessRequest
