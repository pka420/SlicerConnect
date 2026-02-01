import os 
import ctk 
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import logging
import importlib

from Lib.api_client import BackendAPIClient
from Lib.websocket_client import CollaborationWebSocketClient

from datetime import datetime


class CollaborativeSegmentation(ScriptedLoadableModule):
    """
    Main module for collaborative segmentation editing
    """
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Collaborative Segmentation"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Piyush Khurana"]
        self.parent.helpText = """
        This extension enables collaborative editing of segmentations in 3D Slicer.
        Multiple users can work together in real-time on the same segmentation.
        """
        self.parent.acknowledgementText = """
        Developed for collaborative medical image analysis.
        """

class CollaborativeSegmentationWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """
    Main UI widget for the extension
    """
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)

        self.logic = None
        self.api_client = None
        self.ws_client = None

        # State
        self.current_project = None
        self.current_session = None
        self.current_segmentation = None


    def setup(self):
        print('in setup')
        from Lib.api_client import BackendAPIClient

        """Setup the UI"""
        ScriptedLoadableModuleWidget.setup(self)
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/CollaborativeSegmentation.ui"))

        self.logic = CollaborativeSegmentationLogic()

        self.mainCollapsible = ctk.ctkCollapsibleButton()
        self.mainCollapsible.text = "Collaborative Segmentation"
        self.layout.addWidget(self.mainCollapsible)
        mainLayout = qt.QVBoxLayout(self.mainCollapsible)

        statusGroup = qt.QGroupBox("Connection Status")
        statusLayout = qt.QFormLayout(statusGroup)
        mainLayout.addWidget(statusGroup)

        self.statusLabel = qt.QLabel("Checking authentication...")
        self.statusLabel.setStyleSheet("font-weight: bold;")
        statusLayout.addRow("Status:", self.statusLabel)

        self.refreshConnectionButton = qt.QPushButton("Refresh Connection")
        self.refreshConnectionButton.clicked.connect(self._initializeConnection)
        statusLayout.addRow("", self.refreshConnectionButton)

        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.createProjectButton.clicked.connect(self.onCreateProject)
        self.ui.refreshProjectsButton.clicked.connect(self.loadProjects)

        self.ui.projectsList.itemSelectionChanged.connect(self.onProjectSelected)
        self.ui.joinSessionButton.connect('clicked(bool)', self.onJoinSessionClicked)

        self._initializeConnection()

    def onBrowseSegmentation(self):
        file_path = qt.QFileDialog.getOpenFileName(
            None, "Select Segmentation", "", 
            "Volumes (*.nii *.nrrd *.nifti *.mha *.gz)"
        )
        if file_path:
            self.ui.segmentationFileEdit.setText(file_path)
            file_name = os.path.basename(file_path)
            self.logic.load_segmentation(file_path, file_name)

    def _initializeConnection(self):
        """Try to set up API client using existing token"""
        token = slicer.app.settings().value("SlicerConnectToken")
        server_url = slicer.app.settings().value("SlicerConnectServerURL", "http://localhost:8000")
        try:
            self.api_client = BackendAPIClient(server_url, token=token)
            user_info = self.api_client.get_current_user()
            
            if user_info is None:
                self.statusLabel.setText("Authentication failed")
                self.statusLabel.setStyleSheet("color: red;")
                return
            
            self.statusLabel.setText(f"Connected as {user_info.get('username')}")
            self.statusLabel.setStyleSheet("color: green; font-weight: bold;")
            
        except Exception as e:
            self.statusLabel.setText("Connection failed")
            self.statusLabel.setStyleSheet("color: red;")
            print(f"Connection error: {str(e)}")

    def onCreateProject(self):
        print('creating project')
        if not self.api_client:
            slicer.util.errorDisplay("Not connected to server")
            return

        projectName = self.ui.newProjectNameEdit.text.strip()
        description = self.ui.newProjectDescEdit.toPlainText().strip()

        print(projectName, description)

        self.api_client.create_project(projectName, description)

    def loadProjects(self):
        print('loading projects')
        if not self.api_client:
            slicer.util.errorDisplay("Not connected to server")
            return

        projects = self.api_client.list_projects()
        print(projects)

        self.ui.projectsList.clear()
        for project in projects:
            item = qt.QTreeWidgetItem(self.ui.projectsList)
            item.setText(0, project['name'])
            item.setText(1, project['role'].capitalize())
            date_str = project['updated_at']
            item.setText(2, self.format_date(date_str))
            date_str = project['created_at']
            item.setText(3, self.format_date(date_str))
            status = self.get_project_status(project)
            item.setText(4, status)
            item.setData(0, qt.Qt.UserRole, project['id'])
            self.ui.projectsList.addTopLevelItem(item)
        
        for i in range(4):
            self.ui.projectsList.resizeColumnToContents(i)

    def onProjectSelected(self):
        selectedItems = self.ui.projectsList.selectedItems()
        
        if not selectedItems:
            self.ui.joinSessionButton.enabled = False
            return
        
        selectedItem = selectedItems[0]
        
        updated_at = selectedItem.text(2)
        
        if updated_at != "Never":
            self.ui.joinSessionButton.setText("Continue Editing")
        else:
            self.ui.joinSessionButton.setText("Start Editing")
        
        self.ui.joinSessionButton.enabled = True

        self.displaySegmentations(selectedItem)
        self.displayCollabStuff(selectedItem)

    def displaySegmentations(self, projectItem):
        project_id = projectItem.data(0, qt.Qt.UserRole)  
        segs = self.api_client.list_segmentations(project_id)
        print(segs)
        #display in ui

    def displayCollabStuff(self, projectItem):
        project_id = projectItem.data(0, qt.Qt.UserRole)  
        project_details = self.api_client.get_project_details(project_id)
        collaborators = project_details.get('collaborators', [])
        collaboratorNames = [c.get('username', 'Unknown') for c in collaborators]
        collaboratorText = ', '.join(collaboratorNames) if collaboratorNames else 'No collaborators'
        # self.ui.collaboratorsLabel.setText(f"Collaborators: {collaboratorText}")
        print(f"Collaborators: {collaboratorText}")
        
        segCount = project_details.get('segmentation_count', 0)
        print(f"Segmentation count: {segCount}")
        #display this in the ui once you have time..
        
        return False

    def onJoinSessionClicked(self):
        selectedItems = self.ui.projectsList.selectedItems()
        selectedItem = selectedItems[0] 

        session_id = selectedItem.data(0, qt.Qt.UserRole)
        slicer.app.settings().setValue("SlicerConnectSessionId", session_id)
        slicer.app.settings().sync()

        slicer.util.selectModule("SlicerConnectEditor")
        return

    def format_date(self, date_str):
        """Format ISO date string to readable format."""
        if not date_str:
            return 'Never'
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y')
        except:
            return date_str

    def get_project_status(self, project):
        """Determine project status string."""
        if project['is_locked']:
            if project['locked_by_username']:
                return f"{project['locked_by_username']}"
            return "Locked"
        return "Active"


class CollaborativeSegmentationLogic(ScriptedLoadableModuleLogic):
    """
    Logic for handling segmentation operations in 3D Slicer
    """
    
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.current_segmentation_node = None
    
    def create_empty_segmentation(self):
        """Create an empty segmentation and return file path"""
        import nrrd
        import numpy as np
        import tempfile
        
        # Create small empty array
        empty_array = np.zeros((10, 10, 10), dtype=np.uint8)
        
        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.nrrd')
        nrrd.write(temp_file.name, empty_array)
        
        return temp_file.name
    
    def load_segmentation(self, file_path, name):
        """Load segmentation into Slicer"""
        # Load the segmentation
        self.current_segmentation_node = slicer.util.loadSegmentation(file_path)
        if self.current_segmentation_node:
            self.current_segmentation_node.SetName(name)
            return True
        return False
    

    def apply_delta(self, delta: dict):
        """
        Apply received delta to current segmentation
        This is placeholder - real implementation depends on your delta format
        """
        if not self.current_segmentation_node:
            logging.warning("No active segmentation node to apply delta")
            return

        # Example: very simplified placeholder
        logging.info(f"Applying delta from other user: {delta}")

        # ── Real implementation ideas ────────────────────────────────────────
        # 1. Label map delta (add/remove voxels)
        # 2. JSON representation of changed segments
        # 3. Binary mask difference
        # 4. Use Segment Editor effects programmatically

        # For now just show notification
        slicer.util.infoDisplay("Received collaborative update (delta applied)")

    def send_delta_example(self, ws_client, change_type="add", segment_id=1):
        """Example how to send changes - call from your tools/effects"""
        if not ws_client:
            return

        example_delta = {
            "type": change_type,
            "segment_id": segment_id,
            "timestamp": slicer.util.currentTime(),
            # ... voxels, mask, transform, etc. ...
        }
        ws_client.send_delta(example_delta)
