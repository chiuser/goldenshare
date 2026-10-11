"""Source exception identity, independent of resource assembly and Dagster."""


class TushareResponseError(RuntimeError):
    """SDK returned no fields: an empty business response has not been proved."""
