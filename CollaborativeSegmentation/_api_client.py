# CollaborativeSegmentation/api_client.py
import requests
from typing import Dict, Any, Optional, List
import json


class BackendAPIClient:
    """Client for communicating with FastAPI backend"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.token: Optional[str] = None
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def login(self, username: str, password: str) -> bool:
        """Authenticate user and get JWT token"""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"username": username, "password": password}
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("access_token")
            return bool(self.token)
        except Exception:
            return False

    def get_current_user(self) -> Dict:
        """Get information about currently logged-in user"""
        response = self.session.get(
            f"{self.base_url}/users/me",
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    # ── Projects ──────────────────────────────────────────────────────────────
    def create_project(self, name: str, description: str = "") -> Dict:
        response = self.session.post(
            f"{self.base_url}/projects",
            json={"name": name, "description": description},
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def list_projects(self) -> List[Dict]:
        response = self.session.get(
            f"{self.base_url}/projects",
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    # ── Segmentations ─────────────────────────────────────────────────────────
    def create_segmentation(self, project_id: str, name: str, color: str, file_path: str) -> Dict:
        files = {"file": (os.path.basename(file_path), open(file_path, "rb"), "application/octet-stream")}
        data = {"name": name, "color": color}

        response = self.session.post(
            f"{self.base_url}/projects/{project_id}/segmentations",
            data={"data": json.dumps(data)},
            files=files,
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def list_segmentations(self, project_id: str) -> List[Dict]:
        response = self.session.get(
            f"{self.base_url}/projects/{project_id}/segmentations",
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def download_segmentation(self, segmentation_id: str) -> str:
        """Download segmentation file and return temporary local path"""
        import tempfile
        response = self.session.get(
            f"{self.base_url}/segmentations/{segmentation_id}/file",
            headers=self._headers(),
            stream=True
        )
        response.raise_for_status()

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.seg.nrrd')
        with open(temp_file.name, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return temp_file.name

    # ── Sessions ──────────────────────────────────────────────────────────────
    def start_session(self, segmentation_id: str, name: str = "") -> Dict:
        response = self.session.post(
            f"{self.base_url}/sessions",
            json={
                "segmentation_id": segmentation_id,
                "name": name or "Unnamed Session"
            },
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def get_active_sessions(self, segmentation_id: str = None) -> List[Dict]:
        params = {"segmentation_id": segmentation_id} if segmentation_id else {}
        response = self.session.get(
            f"{self.base_url}/sessions/active",
            params=params,
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def end_session(self, session_id: str) -> Dict:
        response = self.session.delete(
            f"{self.base_url}/sessions/{session_id}",
            headers=self._headers()
        )
        response.raise_for_status()
        return response.json()
