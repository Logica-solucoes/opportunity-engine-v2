class EngineError(Exception):
    """A failure whose message is in pt-BR and safe to show to the user (no paths, no customer data).

    `check_id` is the stable id of the validation check behind it, when there is one.
    """

    def __init__(self, message: str, check_id: str | None = None):
        super().__init__(message)
        self.check_id = check_id
