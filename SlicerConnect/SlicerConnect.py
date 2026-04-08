import os
import ctk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import logging
from datetime import datetime
import requests
from typing import Dict, Any, Optional, List

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

ROLE_PERMISSIONS = {
    ROLE_OWNER:  {"can_edit": True,  "can_download": True,  "can_manage_collaborators": True,  "can_delete": True},
    ROLE_EDITOR: {"can_edit": True,  "can_download": True,  "can_manage_collaborators": False, "can_delete": False},
    ROLE_VIEWER: {"can_edit": False, "can_download": True,  "can_manage_collaborators": False, "can_delete": False},
}


class BackendAPIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        self.refresh_token = None  

        if token == None:
            slicer.util.selectModule("SlicerConnectLogin")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _handle_response(self, response: requests.Response) -> Any:
        if response.status_code == 401:
            if self._try_refresh_token():
                return None
            else:
                self._handle_auth_failure()
                raise requests.exceptions.HTTPError("Authentication failed", response=response)

        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise requests.exceptions.HTTPError(detail, response=response)

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
                m
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
        slicer.app.settings().setValue("SlicerConnectToken", "")
        slicer.app.settings().setValue("SlicerConnectRefreshToken", "")
        self.token = None
        self.refresh_token = None
        
        slicer.util.errorDisplay("Session expired. Please log in again.")
        slicer.util.selectModule("SlicerConnectLogin")

    def _make_request(self, method: str, url: str, **kwargs) -> Any:
        """Wrapper for all requests with automatic retry on 401"""
        try:
            if 'headers' not in kwargs:
                kwargs['headers'] = {}
            kwargs['headers'].update(self._headers())
            response = self.session.request(method, url, **kwargs)
            handled_response = self._handle_response(response)
            
            if handled_response is None:
                kwargs['headers'].update(self._headers())  
                response = self.session.request(method, url, **kwargs)
                self._handle_response(response)  
            
            return response.json() if response.content else {}
            
        except requests.exceptions.HTTPError as e:
            raise
        except Exception as e:
            print(f"Request error: {str(e)}")
            slicer.util.errorDisplay(f"Request failed: {str(e)}")
            raise

    def get_current_user(self) -> Dict:
        """Get information about currently logged-in user"""
        info =  self._make_request('GET', f"{self.base_url}/users/me")
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

    def get_project_details(self, project_id) -> Dict:
        return self._make_request('GET', f"{self.base_url}/projects/{project_id}")

    def delete_project(self, project_id) -> Dict:
        return self._make_request('DELETE', f"{self.base_url}/projects/{project_id}")

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
            f"{self.base_url}/segmentations/projects/{project_id}"
        )

    def download_segmentation(self, segmentation_id: str) -> str:
        """Download segmentation file and return temporary local path"""
        import tempfile
        
        try:
            headers = self._headers()
            response = self.session.get(
                f"{self.base_url}/segmentations/{segmentation_id}/download",
                headers=headers,
                stream=True
            )
            
            if response.status_code == 401:
                if self._try_refresh_token():
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

    def get_all_users(self) -> List[Dict]:
        return self._make_request('GET', f"{self.base_url}/users/all-users")

    def get_project_collaborators(self, project_id) -> List[Dict]:                                                                                                                                                 
        return self._make_request(                                                                                                                                                                                 
            'GET',                                                                                                                                                                                                 
            f"{self.base_url}/projects/{project_id}/collaborators"
        )                                           
                                                    
    def add_project_collaborator(self, project_id, user_id: int, role: str) -> Dict:
        return self._make_request(
            'POST',                                 
            f"{self.base_url}/projects/{project_id}/collaborators",  
            json={"user_id": user_id, "role": role}               
        )                                                                                                
                                                    
    def change_collaborator_role(self, project_id, user_id: int, role: str) -> Dict:
        print("sending request to change collaborators")
        print("args: ", project_id, user_id, role)
        return self._make_request(                  
            'PATCH',                                
            f"{self.base_url}/projects/{project_id}/collaborators/{user_id}",
            json={"role": role}                 
        )                                                                                                
                                                    
    def remove_project_collaborator(self, project_id, user_id: int) -> Dict:
        return self._make_request(                  
            'DELETE',                               
            f"{self.base_url}/projects/{project_id}/collaborators/{user_id}"
        )                                                                                                
                                                                                                         
    def get_segmentation(self, segmentation_id: str) -> Dict:
        return self._make_request(                  
            'GET',                                                                                       
            f"{self.base_url}/segmentations/{segmentation_id}"
        )                                                                                                
                                                    
    def get_segmentation_versions(self, segmentation_id: str) -> List[Dict]:
        return self._make_request(                                                                       
            'GET',                                  
            f"{self.base_url}/segmentations/{segmentation_id}/versions"
        )                                           
                                                    
    def upload_segmentation(self, file_path: str) -> Dict:
        files = {"file": (os.path.basename(file_path), open(file_path, "rb"), "application/octet-stream")}
                                                    
        return self._make_request(
            'POST',                                 
            f"{self.base_url}/segmentations/",                                                           
            files=files                                                                                  
        )

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

def get_permissions(role: str) -> dict:
    return ROLE_PERMISSIONS.get(role.lower(), ROLE_PERMISSIONS[ROLE_VIEWER])


class SlicerConnect(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerConnect"
        self.parent.categories = ["Collaborative Segmentation Editor"]
        self.parent.dependencies = []
        self.parent.contributors = ["Piyush Khurana"]
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


class SlicerConnectWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.api_client = None
        self.current_project = None
        self.current_project_name = None
        self.current_project_role = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        self.logic = SlicerConnectLogic()

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/SlicerConnect.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.manageCollabButton.clicked.connect(self.onManageCollaboratorsClicked)

        self._buildStatusBar()
        self._connectSignals()
        self._initializeConnection()

    def onManageCollaboratorsClicked(self):
        if not self.current_project:
            return
        dialog = ManageCollaboratorsDialog(self.api_client, self.current_project, self.current_project_name, self.parent)
        dialog.exec()

    def _buildStatusBar(self):
        statusGroup = qt.QGroupBox("Connection Status")
        statusLayout = qt.QFormLayout(statusGroup)

        self.statusLabel = qt.QLabel("Checking authentication...")
        self.statusLabel.setStyleSheet("font-weight: bold;")
        statusLayout.addRow("Status:", self.statusLabel)

        self.refreshConnectionButton = qt.QPushButton("Refresh Connection")
        self.refreshConnectionButton.clicked.connect(self._initializeConnection)
        statusLayout.addRow("", self.refreshConnectionButton)

        self.layout.insertWidget(0, statusGroup)

    def _connectSignals(self):
        self.ui.createProjectButton.clicked.connect(self.onCreateProject)
        self.ui.refreshProjectsButton.clicked.connect(self.loadProjects)
        self.ui.projectsList.itemSelectionChanged.connect(self.onProjectSelected)
        self.ui.joinSessionButton.connect('clicked(bool)', self.onJoinSessionClicked)
        self.ui.downloadSegButton.connect('clicked(bool)', self.onDownloadSegClicked)
        self.ui.delProjectButton.connect('clicked(bool)', self.onDeleteProjectClicked)
        self.ui.projectTabs.currentChanged.connect(self._onTabChanged)

    def _initializeConnection(self):
        token = slicer.app.settings().value("SlicerConnectToken")
        server_url = slicer.app.settings().value("SlicerConnectServerURL", "https://slicerconnect.from-delhi.net")
        try:
            self.api_client = BackendAPIClient(server_url, token=token)
            user_info = self.api_client.get_current_user()
            slicer.app.settings().setValue("SlicerConnectUser", user_info)
            slicer.app.settings().sync()

            if user_info is None:
                self._setStatus("Authentication failed", "red")
                return

            self._setStatus(f"Connected as {user_info.get('username')}", "green")

        except Exception as e:
            self._setStatus("Connection failed", "red")
            print(f"Connection error: {str(e)}")

    def _setStatus(self, text: str, color: str):
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(f"color: {color}; font-weight: bold;")

    def onCreateProject(self):
        if not self.api_client:
            slicer.util.errorDisplay("Not connected to server")
            return

        name = self.ui.newProjectNameEdit.text.strip()
        description = self.ui.newProjectDescEdit.toPlainText().strip()
        self.api_client.create_project(name, description)

    def loadProjects(self):
        if not self.api_client:
            slicer.util.errorDisplay("Not connected to server")
            return

        projects = self.api_client.list_projects()
        self.ui.projectsList.clear()

        for project in projects:
            item = qt.QTreeWidgetItem(self.ui.projectsList)
            item.setText(0, project['name'])
            item.setText(1, project['role'].capitalize())
            item.setText(2, self.logic.format_date(project['updated_at']))
            item.setText(3, self.logic.format_date(project['created_at']))
            item.setText(4, self.logic.get_project_status(project))
            item.setData(0, qt.Qt.UserRole, project['id'])
            item.setData(1, qt.Qt.UserRole, project['role'])
            item.setData(2, qt.Qt.UserRole, project['name'])
            self.ui.projectsList.addTopLevelItem(item)

        for i in range(5):
            self.ui.projectsList.resizeColumnToContents(i)

    def onProjectSelected(self):
        selectedItems = self.ui.projectsList.selectedItems()

        if not selectedItems:
            self._clearProjectDetails()
            return

        selectedItem = selectedItems[0]
        project_id = selectedItem.data(0, qt.Qt.UserRole)
        role = selectedItem.data(1, qt.Qt.UserRole) or ROLE_VIEWER

        self.current_project = project_id
        self.current_project_name = selectedItem.data(2, qt.Qt.UserRole)
        self.current_project_role = role

        perms = get_permissions(role)

        self.ui.joinSessionButton.enabled = perms["can_edit"]
        self.ui.downloadSegButton.enabled = perms["can_download"]
        self.ui.delProjectButton.enabled = perms["can_delete"]

        updated_at = selectedItem.text(2)
        self.ui.joinSessionButton.setText("Continue Editing" if updated_at != "Never" else "Start Editing")

        self._loadSegmentations(project_id)
        self._loadCollaborators(project_id, perms)

    def _clearProjectDetails(self):
        self.current_project = None
        self.current_project_role = None
        self.ui.joinSessionButton.enabled = False
        self.ui.downloadSegButton.enabled = False
        self.ui.segmentationsList.clear()

    def _loadSegmentations(self, project_id):
        segs = self.api_client.list_segmentations(project_id)
        self.ui.segmentationsList.clear()
        for seg in segs:
            item = qt.QListWidgetItem(seg.get('name', 'Unnamed'))
            item.setData(qt.Qt.UserRole, seg.get('id'))
            self.ui.segmentationsList.addItem(item)

    def _loadCollaborators(self, project_id, perms: dict):
        project_details = self.api_client.get_project_details(project_id)
        collaborators = project_details.get('collaborators', [])
        names = [c.get('username', 'Unknown') for c in collaborators]
        print(f"Collaborators: {', '.join(names) if names else 'None'}")
        print(f"Segmentation count: {project_details.get('segmentation_count', 0)}")

        if perms["can_manage_collaborators"]:
            self._enableCollaboratorManagement(project_id, collaborators)
        else:
            self._disableCollaboratorManagement()

    def _enableCollaboratorManagement(self, project_id, collaborators):
        if hasattr(self.ui, 'manageCollabButton'):
            self.ui.manageCollabButton.enabled = True
            self.ui.manageCollabButton.setToolTip("")

    def _disableCollaboratorManagement(self):
        if hasattr(self.ui, 'manageCollabButton'):
            self.ui.manageCollabButton.enabled = False
            self.ui.manageCollabButton.setToolTip("Only owners can manage collaborators")

    def onJoinSessionClicked(self):
        if not self.current_project:
            return

        perms = get_permissions(self.current_project_role or ROLE_VIEWER)
        if not perms["can_edit"]:
            slicer.util.errorDisplay("You do not have permission to edit this project.")
            return

        slicer.app.settings().setValue("SlicerConnectSessionId", self.current_project)
        slicer.app.settings().sync()
        slicer.util.selectModule("SlicerConnectEditor")

    def onDownloadSegClicked(self):
        if not self.current_project:
            return

        perms = get_permissions(self.current_project_role or ROLE_VIEWER)
        if not perms["can_download"]:
            slicer.util.errorDisplay("You do not have permission to download segmentations.")
            return

        selectedSegs = self.ui.segmentationsList.selectedItems()
        if not selectedSegs:
            slicer.util.errorDisplay("Please select a segmentation to download.")
            return

        seg_id = selectedSegs[0].data(qt.Qt.UserRole)
        try:
            local_path = self.api_client.download_segmentation(seg_id)
            self.logic.load_segmentation(local_path, selectedSegs[0].text())
        except Exception as e:
            slicer.util.errorDisplay(f"Download failed: {str(e)}")

    def onDeleteProjectClicked(self):
        if not self.current_project:
            return

        perms = get_permissions(self.current_project_role or ROLE_EDITOR)
        if not perms["can_delete"]:
            slicer.util.errorDisplay("You do not have permission to delete this Project.")
            return

        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("Are you sure you want to delete this project?")
        msg.setInformativeText(
            "All associated segmentations, data, and collaborators will be permanently deleted. "
            "This action cannot be undone."
        )
        msg.setWindowTitle("Confirm Project Deletion")
        
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.Cancel)
        msg.setDefaultButton(qt.QMessageBox.Cancel) 
        response = msg.exec_()
        
        if response == qt.QMessageBox.Yes:
            print("User confirmed. Proceeding with API call to delete...")
            try:
                self.api_client.delete_project(self.current_project)
            except Exception as e:
                slicer.util.errorDisplay(f"Failed to delete project {self.current_project_name}: {str(e)}")

    def _onTabChanged(self, index):
        if self.ui.projectTabs.tabText(index) == "My Projects" and self.api_client:
            self.loadProjects()


class SlicerConnectLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.current_segmentation_node = None

    def format_date(self, date_str: str) -> str:
        if not date_str:
            return 'Never'
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y')
        except Exception:
            return date_str

    def get_project_status(self, project: dict) -> str:
        if project.get('is_locked'):
            locked_by = project.get('locked_by_username')
            return locked_by if locked_by else "Locked"
        return "Active"

    def load_segmentation(self, file_path: str, name: str) -> bool:
        self.current_segmentation_node = slicer.util.loadSegmentation(file_path)
        if self.current_segmentation_node:
            self.current_segmentation_node.SetName(name)
            return True
        return False

    def apply_delta(self, delta: dict):
        if not self.current_segmentation_node:
            logging.warning("No active segmentation node to apply delta")
            return
        logging.info(f"Applying delta: {delta}")
        slicer.util.infoDisplay("Received collaborative update (delta applied)")

    def send_delta_example(self, ws_client, change_type: str = "add", segment_id: int = 1):
        if not ws_client:
            return
        delta = {
            "type": change_type,
            "segment_id": segment_id,
            "timestamp": slicer.util.currentTime(),
        }
        ws_client.send_delta(delta)


class ManageCollaboratorsDialog(qt.QDialog):
    def __init__(self, api_client, project_id, project_name, parent=None):
        qt.QDialog.__init__(self, parent)
        self.api_client = api_client
        self.project_id = project_id
        self.project_name = project_name
        self.pending_role_changes = {}
        self.setWindowTitle("Manage Collaborators")
        self.setMinimumWidth(480)
        self._build()
        self._refresh()

    def _build(self):
        layout = qt.QVBoxLayout(self)

        tabs = qt.QTabWidget()
        layout.addWidget(tabs)

        rolesTab = qt.QWidget()
        rolesLayout = qt.QVBoxLayout(rolesTab)

        self.table = qt.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Username", "Role", ""])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, qt.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, qt.QHeaderView.ResizeToContents)
        self.table.setSelectionMode(qt.QAbstractItemView.NoSelection)
        self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        rolesLayout.addWidget(self.table)

        self.saveBtn = qt.QPushButton("Save Changes")
        self.saveBtn.enabled = False
        self.saveBtn.setStyleSheet("background-color: #2a82da; color: white;")
        self.saveBtn.clicked.connect(lambda _: self._onSave())
        rolesLayout.addWidget(self.saveBtn)

        tabs.addTab(rolesTab, "Change Roles")

        addTab = qt.QWidget()
        addLayout = qt.QVBoxLayout(addTab)

        formLayout = qt.QFormLayout()

        self.userCombo = qt.QComboBox()
        formLayout.addRow("User:", self.userCombo)

        self.roleCombo = qt.QComboBox()
        self.roleCombo.addItems([ROLE_EDITOR.capitalize(), ROLE_VIEWER.capitalize()])
        formLayout.addRow("Role:", self.roleCombo)

        addLayout.addLayout(formLayout)

        addBtn = qt.QPushButton("Add Collaborator")
        addBtn.clicked.connect(self._onAdd)
        addLayout.addWidget(addBtn)

        addLayout.addStretch()
        tabs.addTab(addTab, "Add Collaborator")


        closeBtn = qt.QPushButton("Close")
        closeBtn.clicked.connect(lambda _: self.close())
        layout.addWidget(closeBtn)


    def _refresh(self):
        try:
            collaborators = self.api_client.get_project_collaborators(self.project_id)
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to load collaborators: {str(e)}")
            return

        self.table.setRowCount(0)
        for collab in collaborators:
            row = self.table.rowCount
            self.table.insertRow(row)

            self.table.setItem(row, 0, qt.QTableWidgetItem(collab.get('username', 'Unknown')))

            roleCombo = qt.QComboBox()
            roleCombo.addItems([ROLE_EDITOR.capitalize(), ROLE_VIEWER.capitalize()])
            current_role = collab.get('role', ROLE_VIEWER).capitalize()
            roleCombo.setCurrentText(current_role)
            user_id = collab.get('user_id')

            roleCombo.currentTextChanged.connect(lambda text, uid=user_id: self._onRoleChanged(uid, text))
            self.table.setCellWidget(row, 1, roleCombo)

            removeBtn = qt.QPushButton("Remove")
            removeBtn.clicked.connect(lambda checked, uid=user_id: self._onRemove(uid))
            self.table.setCellWidget(row, 2, removeBtn)

        try:
            all_users = self.api_client.get_all_users()
            existing_ids = {collab.get('id') for collab in collaborators}
            self.userCombo.clear()
            for user in all_users:
                if user['id'] not in existing_ids:
                    self.userCombo.addItem(f"{user['username']} ({user['email']})", user['id'])
        except Exception as e:
            print(f"Failed to load users: {str(e)}")

    def _onRoleChanged(self, user_id: int, role_text: str):
        self.pending_role_changes[user_id] = role_text.lower()
        self.saveBtn.enabled = True
    
    def _onSave(self):
        errors = []
        for user_id, role in self.pending_role_changes.items():
            try:
                self.api_client.change_collaborator_role(self.project_id, user_id, role)
            except Exception as e:
                errors.append(str(e))

        if errors:
            slicer.util.errorDisplay("Some changes failed:\n" + "\n".join(errors))
        else:
            self.pending_role_changes.clear()
            slicer.util.infoDisplay(f"Roles updated successfully.")
            self.saveBtn.enabled = False
            self._refresh()

    def _onRemove(self, user_id: int):
        confirm = qt.QMessageBox.question(
            self,
            "Remove Collaborator",
            "Are you sure you want to remove this collaborator?",
            qt.QMessageBox.Yes | qt.QMessageBox.No
        )
        if confirm != qt.QMessageBox.Yes:
            return
        try:
            self.api_client.remove_project_collaborator(self.project_id, user_id)
            username = self.userCombo.currentText
            slicer.util.infoDisplay(f"{username} removed from Project {self.project_name} successfully.")
            self._refresh()
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to remove collaborator: {str(e)}")

    def _onAdd(self):
        user_id = self.userCombo.currentData
        if user_id is None:
            slicer.util.errorDisplay("No users available to add.")
            return

        role = self.roleCombo.currentText
        try:
            self.api_client.add_project_collaborator(self.project_id, user_id, role)
            username = self.userCombo.currentText
            slicer.util.infoDisplay(f"{username} added to Project {self.project_name} as {role} successfully.")
            self._refresh()
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to add collaborator: {str(e)}")
