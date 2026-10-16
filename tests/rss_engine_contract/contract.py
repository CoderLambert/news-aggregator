"""Small executable probes, not the production adapter or a publisher client."""
from miniflux import Client

MAX_ID = 2**63 - 1


def page_parameters(lower, upper, limit=100):
    if not (type(lower) is int and type(upper) is int and 0 <= lower <= upper < MAX_ID):
        raise ValueError("invalid or unrepresentable ID interval")
    if not (type(limit) is int and 1 <= limit <= 1000):
        raise ValueError("invalid page size")
    return dict(order="id", direction="asc", after_entry_id=lower,
                before_entry_id=upper + 1, limit=limit)


def upper_bound(client):
    entries = client.get_entries(order="id", direction="desc", limit=1)["entries"]
    return int(entries[0]["id"]) if entries else 0


class PersistentContentProbe(Client):
    """SDK 1.1.6 lacks update_content. Extend only that fixed SDK endpoint."""

    def persist_content(self, entry_id):
        if type(entry_id) is not int or not 0 < entry_id <= MAX_ID:
            raise ValueError("invalid entry ID")
        response = self._session.get(
            self._get_endpoint(f"/entries/{entry_id}/fetch-content"),
            params={"update_content": "true"}, timeout=self._timeout,
        )
        if response.status_code != 200:
            self._handle_error_response(response)
        response.json()  # A malformed success response must fail, not mean persisted.
        return self.get_entry(entry_id)  # The independent read is the persistence proof.


def isolated_project(config):
    """Never accept a free-form URL, compose path, container, or DB from config."""
    import re
    if set(config) != {"project", "environment"} or config["environment"] != "isolated":
        raise ValueError("explicit isolated config required")
    if not re.fullmatch(r"newshub-rss-t00-[a-f0-9]{12}", config["project"]):
        raise ValueError("T00 project allowlist rejected")
    return config["project"]
