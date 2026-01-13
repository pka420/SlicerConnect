# CollaborativeSegmentation/api_client.py
import requests
from typing import Dict, Any, Optional, List
import json
import slicer


class BackendAPIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.refresh_token = None  

        if token == None:
            slicer.util.selectModule("Login")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _handle_response(self, response: requests.Response) -> Any:
        """Interceptor-like handler for all responses"""
        if response.status_code == 401:
            if self._try_refresh_token():
                return None
            else:
                self._handle_auth_failure()
                raise requests.exceptions.HTTPError("Authentication failed", response=response)
        
        response.raise_for_status()
        return response

    def _try_refresh_token(self) -> bool:
        """Attempt to refresh the access token using refresh token"""
        try:
            refresh_token = slicer.app.settings().value("SlicerConnectRefreshToken")
            if not refresh_token:
                return False
            
            response = self.session.post(
                f"{self.base_url}/auth/refresh",
                json={"refresh_token": refresh_token}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token")
                new_refresh = data.get("refresh_token")
                
                slicer.app.settings().setValue("SlicerConnectToken", self.token)
                if new_refresh:
                    slicer.app.settings().setValue("SlicerConnectRefreshToken", new_refresh)
                
                print("Token refreshed successfully")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"Token refresh failed: {str(e)}")
            return False

    def _handle_auth_failure(self):
        """Handle authentication failure - clear tokens and switch to login"""
        print("Authentication failed - clearing tokens")
        
        # Clear tokens
        slicer.app.settings().setValue("SlicerConnectToken", "")
        slicer.app.settings().setValue("SlicerConnectRefreshToken", "")
        self.token = None
        self.refresh_token = None
        
        # Show error and switch to login
        slicer.util.errorDisplay("Session expired. Please log in again.")
        slicer.util.selectModule("Login")

    def _make_request(self, method: str, url: str, **kwargs) -> Any:
        """Wrapper for all requests with automatic retry on 401"""
        try:
            # Add headers
            if 'headers' not in kwargs:
                kwargs['headers'] = {}
            kwargs['headers'].update(self._headers())
            
            # Make request
            response = self.session.request(method, url, **kwargs)
            
            # Handle response (includes 401 check)
            handled_response = self._handle_response(response)
            
            # If handled_response is None, token was refreshed - retry once
            if handled_response is None:
                kwargs['headers'].update(self._headers())  # Update with new token
                response = self.session.request(method, url, **kwargs)
                self._handle_response(response)  # Will raise if still fails
            
            return response.json() if response.content else {}
            
        except requests.exceptions.HTTPError as e:
            # Already handled in _handle_response
            raise
        except Exception as e:
            print(f"Request error: {str(e)}")
            slicer.util.errorDisplay(f"Request failed: {str(e)}")
            raise

    # ── API Methods using the interceptor ────────────────────────────────────

    def get_current_user(self) -> Dict:
        """Get information about currently logged-in user"""
        info =  self._make_request('GET', f"{self.base_url}/auth/users/me")
        print(info)
        return info

    def create_project(self, name: str, description: str = "") -> Dict:
        return self._make_request(
            'POST',
            f"{self.base_url}/projects",
            json={"name": name, "description": description}
        )

    def list_projects(self) -> List[Dict]:
        return self._make_request('GET', f"{self.base_url}/projects")

    def create_segmentation(self, project_id: str, name: str, color: str, file_path: str) -> Dict:
        import os
        files = {"file": (os.path.basename(file_path), open(file_path, "rb"), "application/octet-stream")}
        data = {"name": name, "color": color}

        return self._make_request(
            'POST',
            f"{self.base_url}/projects/{project_id}/segmentations",
            data={"data": json.dumps(data)},
            files=files
        )

    def list_segmentations(self, project_id: str) -> List[Dict]:
        return self._make_request(
            'GET',
            f"{self.base_url}/projects/{project_id}/segmentations"
        )

    def download_segmentation(self, segmentation_id: str) -> str:
        """Download segmentation file and return temporary local path"""
        import tempfile
        
        try:
            # Add headers manually for streaming
            headers = self._headers()
            response = self.session.get(
                f"{self.base_url}/segmentations/{segmentation_id}/file",
                headers=headers,
                stream=True
            )
            
            # Handle 401
            if response.status_code == 401:
                if self._try_refresh_token():
                    # Retry with new token
                    headers = self._headers()
                    response = self.session.get(
                        f"{self.base_url}/segmentations/{segmentation_id}/file",
                        headers=headers,
                        stream=True
                    )
                else:
                    self._handle_auth_failure()
                    raise requests.exceptions.HTTPError("Authentication failed")
            
            response.raise_for_status()

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.seg.nrrd')
            with open(temp_file.name, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return temp_file.name
            
        except Exception as e:
            print(f"Download error: {str(e)}")
            slicer.util.errorDisplay(f"Failed to download segmentation: {str(e)}")
            raise

    # ── Sessions ──────────────────────────────────────────────────────────────
    def start_session(self, segmentation_id: str, name: str = "") -> Dict:
        return self._make_request(
            'POST',
            f"{self.base_url}/sessions",
            json={
                "segmentation_id": segmentation_id,
                "name": name or "Unnamed Session"
            }
        )

    def get_active_sessions(self, segmentation_id: str = None) -> List[Dict]:
        params = {"segmentation_id": segmentation_id} if segmentation_id else {}
        return self._make_request(
            'GET',
            f"{self.base_url}/sessions/active",
            params=params
        )

    def end_session(self, session_id: str) -> Dict:
        return self._make_request(
            'DELETE',
            f"{self.base_url}/sessions/{session_id}"
        )
