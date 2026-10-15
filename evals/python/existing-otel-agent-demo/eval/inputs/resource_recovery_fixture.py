"""Studio resource fixture with real 201 replies and externally rotated IDs."""

from studio_resources import ResourceHandler, ResourceServer


class CreatedResourceHandler(ResourceHandler):
    def resolve(self, method, body):
        status, response = super().resolve(method, body)
        if method == "POST" and status == 200:
            return 201, response
        return status, response


class RecoveryServer(ResourceServer):
    def __init__(self, scenario="missing", journal_path=None):
        super().__init__(scenario, journal_path)
        self.RequestHandlerClass = CreatedResourceHandler

    def rotate_identities(self):
        with self.lock:
            self.projects = [{
                "id": "f3370c1b-4bca-4a57-afee-812bb7ab9010",
                "name": "fixture-project",
            }]
            self.streams = [{
                "id": "b9b4b5ce-5e85-424a-8b42-70992265d010",
                "name": "fixture-agent",
                "project_id": self.projects[0]["id"],
            }]
