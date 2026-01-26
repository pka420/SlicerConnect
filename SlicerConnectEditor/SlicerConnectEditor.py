import os
import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np
import json
import base64

try:
    from websocket import WebSocketApp
    import threading
except ImportError:
    slicer.util.pip_install('websocket-client')
    from websocket import WebSocketApp
    import threading


class SlicerConnectEditor(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerConnectEditor"
        self.parent.categories = ["IGT"]
        self.parent.dependencies = []
        self.parent.contributors = ["Your Name"]
        self.parent.helpText = """
Real-time multi-user segmentation collaboration using WebSocket and OpenIGTLink.
"""
        self.parent.acknowledgementText = """
Developed for collaborative medical image segmentation.
"""


class SlicerConnectEditorWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.segmentationNode = None
        self.observerTags = []
        self.ui = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = SlicerConnectEditorLogic()

        uiWidget = slicer.util.loadUI(self.resourcePath('UI/SlicerConnectEditor.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.setupConnections()
        
        self.setupSegmentEditor()

    def setupConnections(self):
        self.ui.refreshConnectionButton.clicked.connect(self.onConnect)
        token = slicer.app.settings().value('SlicerConnectToken')
        tokenStatus = "Found" if token else "Not Found"
        self.ui.tokenLabel.setText(tokenStatus)

    def setupSegmentEditor(self):
        self.ui.editorWidget.setMaximumNumberOfUndoStates(10)
        self.ui.editorWidget.setMRMLScene(slicer.mrmlScene)
        
        segment_editor_singleton_tag = "SegmentEditor"
        self.segment_editor_node = slicer.mrmlScene.GetSingletonNode(
            segment_editor_singleton_tag, "vtkMRMLSegmentEditorNode"
        )
        
        if self.segment_editor_node is None:
            self.segment_editor_node = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSegmentEditorNode")
            self.segment_editor_node.UnRegister(None)
            self.segment_editor_node.SetSingletonTag(segment_editor_singleton_tag)
            self.segment_editor_node = slicer.mrmlScene.AddNode(self.segment_editor_node)
        
        self.ui.editorWidget.setMRMLSegmentEditorNode(self.segment_editor_node)

    def cleanup(self):
        self.removeObservers()
        if self.logic:
            self.logic.disconnect()

    def onConnect(self):
        sessionId = self.ui.sessionIdSpinBox.value
        baseUrl = self.ui.wsUrlLineEdit.text
        
        token = slicer.app.settings().value('SlicerConnectToken')
        if not token:
            slicer.util.errorDisplay("Authentication token not found. Please login first.")
            self.addLog("ERROR: No authentication token found")
            return

        self.addLog(f"Connecting to session {sessionId}...")
        success = self.logic.connect(baseUrl, sessionId, token)
        
        if success:
            self.ui.statusLabel.setText(f"Connected to Session {sessionId}")
            self.ui.connectButton.setEnabled(False)
            self.ui.disconnectButton.setEnabled(True)
            self.ui.wsUrlLineEdit.setEnabled(False)
            self.ui.sessionIdSpinBox.setEnabled(False)
            self.addLog("Connected successfully")
        else:
            self.ui.statusLabel.setText("Connection Failed")
            self.addLog("ERROR: Connection failed")

    def onDisconnect(self):
        self.logic.disconnect()
        self.ui.statusLabel.setText("Disconnected")
        self.ui.connectButton.setEnabled(True)
        self.ui.disconnectButton.setEnabled(False)
        self.ui.wsUrlLineEdit.setEnabled(True)
        self.ui.sessionIdSpinBox.setEnabled(True)
        self.ui.syncCheckBox.setChecked(False)
        self.addLog("Disconnected")

    def onSegmentationSelected(self, node):
        if self.segmentationNode:
            self.removeObservers()
        
        self.segmentationNode = node
        self.logic.setSegmentationNode(node)
        self.ui.editorWidget.setSegmentationNode(node)
        
        if node and self.ui.syncCheckBox.isChecked():
            self.addObserver(node, vtk.vtkCommand.ModifiedEvent, self.onSegmentationModified)

    def onSyncChanged(self, state):
        if state and self.segmentationNode:
            self.addObserver(
                self.segmentationNode, 
                vtk.vtkCommand.ModifiedEvent, 
                self.onSegmentationModified
            )
            self.logic.setUserId(self.ui.userIdLineEdit.text)
            self.logic.enableSync(True)
            self.addLog("Sync enabled")
        else:
            self.removeObservers()
            self.logic.enableSync(False)
            self.addLog("Sync disabled")

    def onSegmentationModified(self, caller, event):
        if self.logic.isSyncEnabled():
            self.logic.sendSegmentationUpdate()

    def updateUI(self):
        self.ui.sentLabel.setText(str(self.logic.sentCount))
        self.ui.receivedLabel.setText(str(self.logic.receivedCount))
        self.ui.connectedUsersLabel.setText(str(self.logic.connectedUsers))

    def addLog(self, message):
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.ui.logTextEdit.append(f"[{timestamp}] {message}")

    def resourcePath(self, filename):
        scriptedModulesPath = os.path.dirname(slicer.util.modulePath(self.moduleName))
        return os.path.join(scriptedModulesPath, 'Resources', filename)


class SlicerConnectEditorLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.ws = None
        self.wsThread = None
        self.segmentationNode = None
        self.syncEnabled = False
        self.userId = "User1"
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.isUpdating = False
        self.connected = False

    def connect(self, baseUrl, sessionId, token):
        try:
            wsUrl = f"{baseUrl.rstrip('/')}"
            if "/ws" not in wsUrl:
                wsUrl = f"{baseUrl.rstrip('/')}/ws"
            
            wsUrl = wsUrl.replace("/sessions/1/", f"/sessions/{sessionId}/")
            wsUrl = f"{wsUrl}?token={token}"
            
            print(f"Connecting to: {wsUrl}")
            
            self.ws = WebSocketApp(
                wsUrl,
                on_message=self.onWsMessage,
                on_error=self.onWsError,
                on_close=self.onWsClose,
                on_open=self.onWsOpen
            )
            
            self.wsThread = threading.Thread(target=self.ws.run_forever)
            self.wsThread.daemon = True
            self.wsThread.start()
            
            import time
            timeout = 5
            startTime = time.time()
            while time.time() - startTime < timeout:
                if self.connected:
                    return True
                time.sleep(0.1)
            
            return self.connected
        except Exception as e:
            print(f"Connection error: {str(e)}")
            slicer.util.errorDisplay(f"Connection error: {str(e)}")
            return False

    def disconnect(self):
        self.syncEnabled = False
        self.connected = False
        if self.ws:
            self.ws.close()
            self.ws = None
        if self.wsThread:
            self.wsThread.join(timeout=2)
            self.wsThread = None
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0

    def setSegmentationNode(self, node):
        self.segmentationNode = node

    def setUserId(self, userId):
        self.userId = userId

    def enableSync(self, enabled):
        self.syncEnabled = enabled

    def isSyncEnabled(self):
        return self.syncEnabled and self.connected and self.segmentationNode

    def onWsOpen(self, ws):
        print("WebSocket connection opened")
        self.connected = True
        joinMessage = {
            "type": "join",
            "userId": self.userId,
            "timestamp": self.getCurrentTimestamp()
        }
        ws.send(json.dumps(joinMessage))

    def onWsMessage(self, ws, message):
        try:
            data = json.loads(message)
            msgType = data.get("type")
            print(f"Received message type: {msgType}")
            
            if msgType == "segmentation_update":
                self.handleSegmentationUpdate(data)
            elif msgType == "user_joined":
                print(f"User joined: {data.get('userId')}")
                self.connectedUsers = data.get("totalUsers", 0)
            elif msgType == "user_left":
                print(f"User left: {data.get('userId')}")
                self.connectedUsers = data.get("totalUsers", 0)
            elif msgType == "user_list":
                self.connectedUsers = len(data.get("users", []))
            elif msgType == "error":
                print(f"Server error: {data.get('message')}")
        except Exception as e:
            print(f"Error processing message: {str(e)}")

    def onWsError(self, ws, error):
        print(f"WebSocket error: {error}")
        self.connected = False

    def onWsClose(self, ws, closeStatusCode, closeMsg):
        print(f"WebSocket closed: {closeStatusCode} - {closeMsg}")
        self.connected = False

    def sendSegmentationUpdate(self):
        if not self.isSyncEnabled() or self.isUpdating:
            return

        try:
            labelmapNode = slicer.vtkMRMLLabelMapVolumeNode()
            slicer.mrmlScene.AddNode(labelmapNode)
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                self.segmentationNode, labelmapNode
            )

            imageData = labelmapNode.GetImageData()
            from vtk.util import numpy_support
            arrayData = numpy_support.vtk_to_numpy(imageData.GetPointData().GetScalars())
            dims = imageData.GetDimensions()
            arrayData = arrayData.reshape(dims[2], dims[1], dims[0])

            spacing = labelmapNode.GetSpacing()
            origin = labelmapNode.GetOrigin()

            import zlib
            compressedData = zlib.compress(arrayData.tobytes())
            encodedData = base64.b64encode(compressedData).decode('utf-8')

            message = {
                "type": "segmentation_update",
                "userId": self.userId,
                "timestamp": self.getCurrentTimestamp(),
                "data": {
                    "imageData": encodedData,
                    "dimensions": list(dims),
                    "spacing": list(spacing),
                    "origin": list(origin),
                    "dataType": str(arrayData.dtype)
                }
            }

            self.ws.send(json.dumps(message))
            self.sentCount += 1

            slicer.mrmlScene.RemoveNode(labelmapNode)
            print(f"Sent segmentation update #{self.sentCount}")
        except Exception as e:
            print(f"Error sending segmentation: {str(e)}")

    def handleSegmentationUpdate(self, data):
        if not self.segmentationNode or self.isUpdating:
            return

        if data.get("userId") == self.userId:
            return

        try:
            self.isUpdating = True
            updateData = data.get("data", {})

            import zlib
            encodedData = updateData.get("imageData")
            compressedData = base64.b64decode(encodedData)
            decompressedData = zlib.decompress(compressedData)

            dims = updateData.get("dimensions")
            dataType = updateData.get("dataType")
            arrayData = np.frombuffer(decompressedData, dtype=dataType)
            arrayData = arrayData.reshape(dims[2], dims[1], dims[0])

            labelmapNode = slicer.vtkMRMLLabelMapVolumeNode()
            slicer.mrmlScene.AddNode(labelmapNode)
            labelmapNode.SetName(f"ReceivedSegmentation_{data.get('userId')}")

            from vtk.util import numpy_support
            vtkArray = numpy_support.numpy_to_vtk(arrayData.ravel(), deep=True)
            imageData = vtk.vtkImageData()
            imageData.SetDimensions(dims)
            imageData.GetPointData().SetScalars(vtkArray)
            labelmapNode.SetAndObserveImageData(imageData)
            labelmapNode.SetSpacing(updateData.get("spacing"))
            labelmapNode.SetOrigin(updateData.get("origin"))

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmapNode, self.segmentationNode
            )
            self.receivedCount += 1
            print(f"Received segmentation update #{self.receivedCount} from {data.get('userId')}")

            slicer.mrmlScene.RemoveNode(labelmapNode)
            self.isUpdating = False
        except Exception as e:
            self.isUpdating = False
            print(f"Error receiving segmentation: {str(e)}")

    def getCurrentTimestamp(self):
        import time
        return int(time.time() * 1000)


class SlicerConnectEditorTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_SlicerConnectEditor1()

    def test_SlicerConnectEditor1(self):
        self.delayDisplay("Starting the test")
        logic = SlicerConnectEditorLogic()
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        logic.setSegmentationNode(segmentationNode)
        self.delayDisplay('Test passed!')
