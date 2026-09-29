"""Named diagnostics shared by the SOP compiler components."""


class SOPCError(Exception):
    """Base exception carrying a stable diagnostic code."""

    code = "SOPC-ERROR"


class SOPParseError(SOPCError):
    """A source document does not follow the declared SOP grammar."""

    code = "SOPC-GRAMMAR"

    def __init__(self, filename: str, line: int, rule: str, message: str):
        self.filename = filename
        self.line = line
        self.rule = rule
        self.message = message
        super().__init__(f"{filename}:{line}: {rule}: {message}")


class PlanSchemaError(SOPCError):
    """A JSON document cannot be loaded as the versioned plan schema."""

    code = "SOPC-SCHEMA"

    def __init__(self, rule: str, message: str):
        self.rule = rule
        self.message = message
        super().__init__(f"{rule}: {message}")


class VerificationError(SOPCError):
    """One or more static verification rules rejected a plan."""

    code = "SOPC-VERIFY"

    def __init__(self, violations):
        self.violations = tuple(violations)
        super().__init__("\n".join(str(item) for item in self.violations))


class ExecutionError(SOPCError):
    """Execution stopped because a runtime rule was violated."""

    def __init__(self, code: str, message: str, step_id: str | None = None):
        self.code = code
        self.step_id = step_id
        self.message = message
        where = f" step={step_id}" if step_id else ""
        super().__init__(f"{code}:{where} {message}")
