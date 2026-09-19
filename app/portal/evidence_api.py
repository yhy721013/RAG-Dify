from app.main import create_app
from app.portal.settings import PortalSettings
from app.portal.repository import PortalRepository
from app.repository import Repository


class PortalEvidenceRepository(Repository):
    def __init__(self, config):
        super().__init__(config.evidence_settings().db_path)
        self.portal = PortalRepository(config.db_path)

    def initialize(self):
        super().initialize()
        self.portal.initialize()

    def snapshot_active(self, snapshot_id):
        return (any(row["snapshot_id"] == snapshot_id for row in self.portal.releases())
                and super().snapshot_active(snapshot_id))


config = PortalSettings.from_env()
app = create_app(config.evidence_settings(), PortalEvidenceRepository(config))
