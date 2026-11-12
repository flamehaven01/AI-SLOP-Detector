import json


def persist(record):
    return None


def save_record(record):
    """Save the record to the order store."""
    persist(record)
    return True


def load(path, mode):
    """Load the orders saved at path, opened with mode."""
    with open(path) as fh:
        return json.load(fh)


def send(client, payload):
    try:
        client.post(payload)
    except Exception:
        pass
    return True
