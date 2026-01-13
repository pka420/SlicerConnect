import os
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import logging

from _api_client import BackendAPIClient
from _websocket_client import CollaborationWebSocketClient


class CollaborativeSegmentation(ScriptedLoadableModule):
    """
    Main module for collaborative segmentation editing
    """
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Collaborative Segmentation"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Your Name"]
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
        """Setup the UI"""
        ScriptedLoadableModuleWidget.setup(self)

        self.logic = CollaborativeSegmentationLogic()

        # Main collapsible button
        self.mainCollapsible = ctk.ctkCollapsibleButton()
        self.mainCollapsible.text = "Collaborative Segmentation"
        self.layout.addWidget(self.mainCollapsible)
        mainLayout = qt.QVBoxLayout(self.mainCollapsible)

        # ── Connection & Authentication Status ───────────────────────────────
        statusGroup = qt.QGroupBox("Connection Status")
        statusLayout = qt.QFormLayout(statusGroup)
        mainLayout.addWidget(statusGroup)

        self.statusLabel = qt.QLabel("Checking authentication...")
        self.statusLabel.setStyleSheet("font-weight: bold;")
        statusLayout.addRow("Status:", self.statusLabel)

        self.refreshConnectionButton = qt.QPushButton("Refresh Connection")
        self.refreshConnectionButton.clicked.connect(self._initializeConnection)
        statusLayout.addRow("", self.refreshConnectionButton)

        # Project & Session area
        self.projectGroup = qt.QGroupBox("Projects & Sessions")
        projectLayout = qt.QVBoxLayout(self.projectGroup)
        mainLayout.addWidget(self.projectGroup)
        self.projectGroup.setEnabled(False)

        # Tab widget for project options
        self.projectTabs = qt.QTabWidget()
        projectLayout.addWidget(self.projectTabs)

        self.createProjectTab = self._createNewProjectTab()
        self.projectTabs.addTab(self.createProjectTab, "Create New")

        self.selectProjectTab = self._createSelectProjectTab()
        self.projectTabs.addTab(self.selectProjectTab, "My Projects")

        self.joinLinkTab = self._createJoinLinkTab()
        self.projectTabs.addTab(self.joinLinkTab, "Join via Link")

        # Active Session panel
        self.sessionGroup = qt.QGroupBox("Active Session")
        sessionLayout = qt.QVBoxLayout(self.sessionGroup)
        mainLayout.addWidget(self.sessionGroup)
        self.sessionGroup.setVisible(False)

        self.sessionInfoLabel = qt.QLabel("No active session")
        sessionLayout.addWidget(self.sessionInfoLabel)

        usersLabel = qt.QLabel("Active Users:")
        usersLabel.setStyleSheet("font-weight: bold;")
        sessionLayout.addWidget(usersLabel)

        self.activeUsersList = qt.QListWidget()
        self.activeUsersList.setMaximumHeight(100)
        sessionLayout.addWidget(self.activeUsersList)

        # Session actions
        actionsLayout = qt.QHBoxLayout()
        sessionLayout.addLayout(actionsLayout)

        self.leaveSessionButton = qt.QPushButton("Leave Session")
        self.leaveSessionButton.clicked.connect(self.onLeaveSession)
        actionsLayout.addWidget(self.leaveSessionButton)

        self.endSessionButton = qt.QPushButton("End Session")
        self.endSessionButton.clicked.connect(self.onEndSession)
        actionsLayout.addWidget(self.endSessionButton)

        # Share link
        shareLayout = qt.QHBoxLayout()
        sessionLayout.addLayout(shareLayout)

        self.sessionLinkEdit = qt.QLineEdit()
        self.sessionLinkEdit.setReadOnly(True)
        shareLayout.addWidget(self.sessionLinkEdit)

        self.copyLinkButton = qt.QPushButton("Copy Link")
        self.copyLinkButton.clicked.connect(self.onCopyLink)
        shareLayout.addWidget(self.copyLinkButton)

        self.layout.addStretch(1)

        # Try to initialize connection on startup
        self._initializeConnection()

    def _initializeConnection(self):
        """Try to set up API client using existing token"""
        token = slicer.app.settings().value("SlicerConnect/Token")

        if not token:
            self.statusLabel.setText("No authentication token found")
            self.statusLabel.setStyleSheet("color: orange;")
            self.projectGroup.setEnabled(False)
            slicer.util.warningDisplay(
                "No authentication token found.\n"
                "Please log in using the authentication module first."
            )
            return

        server_url = slicer.app.settings().value("SlicerConnect/ServerURL", "http://localhost:8000")

        try:
            self.api_client = BackendAPIClient(server_url, token=token)

            # Simple token validation / whoami call
            user_info = self.api_client.get_current_user()

            self.statusLabel.setText(f"Connected as {user_info.get('username', 'user')}")
            self.statusLabel.setStyleSheet("color: green; font-weight: bold;")
            self.projectGroup.setEnabled(True)

            self.onRefreshProjects()

        except Exception as e:
            self.statusLabel.setText("Authentication failed")
            self.statusLabel.setStyleSheet("color: red;")
            slicer.util.errorDisplay(f"Cannot connect to server: {str(e)}")
            self.projectGroup.setEnabled(False)

    # ──────────────────────────────────────────────────────────────────────
    #   The rest of the UI creation methods remain almost the same
    # ──────────────────────────────────────────────────────────────────────

    def _createNewProjectTab(self):
        widget = qt.QWidget()
        layout = qt.QFormLayout(widget)

        self.newProjectNameEdit = qt.QLineEdit()
        layout.addRow("Project Name:", self.newProjectNameEdit)

        self.newProjectDescEdit = qt.QTextEdit()
        self.newProjectDescEdit.setMaximumHeight(60)
        layout.addRow("Description:", self.newProjectDescEdit)

        self.newSegmentationNameEdit = qt.QLineEdit()
        layout.addRow("Segmentation Name:", self.newSegmentationNameEdit)

        colorLayout = qt.QHBoxLayout()
        self.segmentationColorButton = qt.QPushButton()
        self.segmentationColorButton.setMaximumWidth(50)
        self.segmentationColorButton.setStyleSheet("background-color: #FF0000;")
        self.segmentationColorButton.clicked.connect(self.onChooseColor)
        self.selectedColor = "#FF0000"
        colorLayout.addWidget(self.segmentationColorButton)
        colorLayout.addWidget(qt.QLabel(self.selectedColor))
        layout.addRow("Color:", colorLayout)

        fileLayout = qt.QHBoxLayout()
        self.segmentationFileEdit = qt.QLineEdit()
        fileLayout.addWidget(self.segmentationFileEdit)
        self.browseFileButton = qt.QPushButton("Browse...")
        self.browseFileButton.clicked.connect(self.onBrowseSegmentationFile)
        fileLayout.addWidget(self.browseFileButton)
        layout.addRow("Initial File:", fileLayout)

        self.createProjectButton = qt.QPushButton("Create & Start Session")
        self.createProjectButton.clicked.connect(self.onCreateProject)
        layout.addRow("", self.createProjectButton)

        return widget

    # ... (keep _createSelectProjectTab(), _createJoinLinkTab() mostly unchanged)

    # ──────────────────────────────────────────────────────────────────────
    #   Important: All API calls should now use self.api_client directly
    #   No more login step!
    # ──────────────────────────────────────────────────────────────────────

    def onCreateProject(self):
        if not self.api_client:
            slicer.util.errorDisplay("Not connected to server")
            return

    def _connectToSession(self, session_id):
        """Connect to WebSocket for collaborative session"""
        # Create WebSocket client
        self.ws_client = CollaborationWebSocketClient(
            self.api_client.base_url.replace("http", "ws"),
            session_id,
            self.api_client.token,
            self.logic
        )
        
        # Set up callbacks
        self.ws_client.on_user_joined = self._onUserJoined
        self.ws_client.on_user_left = self._onUserLeft
        self.ws_client.on_delta_received = self._onDeltaReceived
        self.ws_client.on_session_ended = self._onSessionEnded
        
        # Connect
        self.ws_client.connect()
        
        # Show session UI
        self._showSessionUI()
    
    def _showSessionUI(self):
        """Show the active session UI"""
        self.sessionGroup.setVisible(True)
        self.projectGroup.setEnabled(False)
        
        # Update session info
        session_name = self.current_session.get('session_name', 'Unnamed Session')
        self.sessionInfoLabel.setText(
            f"<b>{session_name}</b><br>"
            f"Segmentation: {self.current_segmentation.get('name', 'Unknown')}"
        )
        
        # Generate and display session link
        session_link = f"collab://session/{self.current_session['session_id']}?token={self.api_client.token}"
        self.sessionLinkEdit.setText(session_link)
    
    def _hideSessionUI(self):
        """Hide the active session UI"""
        self.sessionGroup.setVisible(False)
        self.projectGroup.setEnabled(True)
        self.activeUsersList.clear()
        self.current_session = None
    
    def _onUserJoined(self, username):
        """Handle user joined event"""
        self.activeUsersList.addItem(f"👤 {username}")
    
    def _onUserLeft(self, username):
        """Handle user left event"""
        items = self.activeUsersList.findItems(f"👤 {username}", qt.Qt.MatchExactly)
        for item in items:
            self.activeUsersList.takeItem(self.activeUsersList.row(item))
    
    def _onDeltaReceived(self, delta, username):
        """Handle delta received from another user"""
        # Logic will apply the delta to the segmentation
        pass
    
    def _onSessionEnded(self):
        """Handle session ended event"""
        slicer.util.infoDisplay("Session has been ended by the host")
        self._hideSessionUI()
        if self.ws_client:
            self.ws_client.disconnect()
            self.ws_client = None


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
