class SynclabReleaseError(Exception):
    code = "SYNCLAB_RELEASE_FAILED"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def format(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigError(SynclabReleaseError):
    code = "CONFIG_FAILED"


class PreflightError(SynclabReleaseError):
    code = "PRE_FLIGHT_FAILED"


class BuildError(SynclabReleaseError):
    code = "BUILD_FAILED"


class SignError(SynclabReleaseError):
    code = "SIGN_FAILED"


class VerifyError(SynclabReleaseError):
    code = "VERIFY_FAILED"


class PublishError(SynclabReleaseError):
    code = "PUBLISH_FAILED"
