class AuthenticationError(Exception):
    pass


class EndpointUnavailableError(Exception):
    pass


class EndpointError(Exception):
    pass


class StatusError(Exception):
    pass


class NoNewStatus(Exception):
    pass
