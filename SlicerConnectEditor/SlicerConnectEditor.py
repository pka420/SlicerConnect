import os
import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np
import json
import base64
import hashlib
from datetime import datetime, timezone

from PySide6.QtCore import QTimer, QObject, Signal, QThread
from PySide6.QtNetwork import QWebSocket

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
Real-time multi-user segmentation collaboration using WebSocket with delta updates.
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
        self.sessionId = None
        
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = SlicerConnectEditorLogic()

        uiWidget = slicer.util.loadUI(self.resourcePath('UI/SlicerConnectEditor.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.refreshConnectionButton.clicked.connect(self.checkAndConnectFromSession)
        self.setupSegmentEditor()
        
        self.checkAndConnectFromSession()

    def setupSegmentEditor(self):
        """Setup segment editor with real-time modification tracking"""
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
        
        self.addObserver(
            self.segment_editor_node,
            vtk.vtkCommand.ModifiedEvent,
            self.onSegmentEditorNodeModified
        )

    def checkAndConnectFromSession(self):
        """Check if a session ID was passed and auto-connect"""
        sessionId = slicer.app.settings().value('SlicerConnectSessionId')
        if sessionId:
            try:
                self.sessionId = int(sessionId)
                self.addLog(f"Session ID {self.sessionId} received from previous module")
                self.connectToSession(self.sessionId)
            except (ValueError, TypeError):
                self.addLog("ERROR: Invalid session ID received")
        else:
            qt.QMessageBox.warning(
                slicer.util.mainWindow(),
                "No Session Detected",
                "Select a project first."
            )
            slicer.util.selectModule("CollaborativeSegmentation")

    def connectToSession(self, sessionId):
        """Connect to a specific session"""
        self.sessionId = sessionId
        
        token = slicer.app.settings().value('SlicerConnectToken')
        if not token:
            self.promptLogin()
            return

        self.addLog(f"Connecting to session {sessionId}...")
        success = self.logic.connect(sessionId, token)
        
        if success:
            self.ui.statusLabel.setText(f"Connected to Session {sessionId}")
            self.addLog("Connected successfully")
            self.addLog("Delta-based sync enabled - only changes are sent")
        else:
            self.ui.statusLabel.setText("Connection Failed")
            self.addLog("ERROR: Connection failed")

    def promptLogin(self):
        """Show dialog prompting user to login and redirect to login module"""
        msgBox = qt.QMessageBox()
        msgBox.setIcon(qt.QMessageBox.Warning)
        msgBox.setText("Authentication Required")
        msgBox.setInformativeText("No authentication token found. Please login first.")
        msgBox.setStandardButtons(qt.QMessageBox.Ok)
        msgBox.exec_()
        
        self.addLog("Redirecting to login module...")
        
        try:
            slicer.util.selectModule('SlicerConnectLogin')
        except:
            self.addLog("ERROR: SlicerConnectLogin module not found")

    def onDisconnect(self):
        self.removeObservers()
        self.logic.disconnect()
        self.ui.statusLabel.setText("Disconnected")
        self.addLog("Disconnected")

    def checkSegmentationNode(self):
        """Periodically check if the segmentation node has changed"""
        if self.segment_editor_node:
            currentSegmentationNode = self.segment_editor_node.GetSegmentationNode()
            
            if currentSegmentationNode != self.segmentationNode:
                self.onSegmentationSelected(currentSegmentationNode)
    
    def onSegmentEditorNodeModified(self, caller, event):
        """Called when segment editor node is modified"""
        if self.segment_editor_node:
            currentSegmentationNode = self.segment_editor_node.GetSegmentationNode()
            
            if currentSegmentationNode != self.segmentationNode:
                self.onSegmentationSelected(currentSegmentationNode)
    
    def onSegmentationSelected(self, node):
        """Handle segmentation node selection and setup real-time observers"""
        if self.segmentationNode:
            try:
                self.removeObserver(self.segmentationNode, vtk.vtkCommand.ModifiedEvent, self.onSegmentationModified)
                if self.segmentationNode.GetSegmentation():
                    self.removeObserver(self.segmentationNode.GetSegmentation(), vtk.vtkCommand.ModifiedEvent, self.onSegmentationModified)
                    self.removeObserver(self.segmentationNode.GetSegmentation(), slicer.vtkSegmentation.RepresentationModified, self.onSegmentationModified)
            except:
                pass
        
        self.segmentationNode = node
        self.logic.setSegmentationNode(node)
        
        if node:
            self.addLog(f"Segmentation selected: {node.GetName()}")
            
            self.addObserver(
                node,
                vtk.vtkCommand.ModifiedEvent,
                self.onSegmentationModified
            )
            
            segmentation = node.GetSegmentation()
            if segmentation:
                self.addObserver(
                    segmentation,
                    vtk.vtkCommand.ModifiedEvent,
                    self.onSegmentationModified
                )
                
                self.addObserver(
                    segmentation,
                    slicer.vtkSegmentation.RepresentationModified,
                    self.onSegmentationModified
                )
            
            self.addLog("Real-time delta sync observers added")
        else:
            self.addLog("No segmentation selected")

    def onSegmentationModified(self, caller, event):
        """Called whenever segmentation is modified"""
        if self.logic.connected and not self.logic.isUpdating:
            self.logic.sendSegmentationDelta()
            self.updateUI()

    def updateUI(self):
        """Update UI statistics"""
        self.ui.sentLabel.setText(str(self.logic.sentCount))
        self.ui.receivedLabel.setText(str(self.logic.receivedCount))
        self.ui.connectedUsersLabel.setText(str(self.logic.connectedUsers))

    def addLog(self, message):
        """Add timestamped log message"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.ui.logTextEdit.append(f"[{timestamp}] {message}")

    def cleanup(self):
        """Cleanup when module is closed"""
        self.removeObservers()
        if self.logic:
            self.logic.disconnect()

    def resourcePath(self, filename):
        """Get path to resource file"""
        scriptedModulesPath = os.path.dirname(slicer.util.modulePath(self.moduleName))
        return os.path.join(scriptedModulesPath, 'Resources', filename)

class WebSocketHandler(QObject):
    messageReceived = Signal(str)
    connected = Signal()
    disconnected = Signal()
    errorOccurred = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.ws = None
        
    def connect(self, url):
        self.ws = QWebSocket()
        self.ws.connected.connect(self.onConnected)
        self.ws.disconnected.connect(self.onDisconnected)
        self.ws.textMessageReceived.connect(self.onMessage)
        self.ws.error.connect(self.onError)
        self.ws.open(url)
        
    def onConnected(self):
        self.connected.emit()
        
    def onMessage(self, message):
        self.messageReceived.emit(message)
        
    def onDisconnected(self):
        self.disconnected.emit()
        
    def onError(self):
        self.errorOccurred.emit(self.ws.errorString())
        
    def send(self, message):
        if self.ws:
            self.ws.sendTextMessage(message)

    def isConnected(self):
        return self.connected

            
    def close(self):
        if self.ws:
            self.ws.close()


class SlicerConnectEditorLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.segmentationNode = None
        self.userId = "User1"
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.isUpdating = False
        self.connected = False
        self.WS_BASE_URL = "ws://localhost:8000/collaboration/sessions"

        self.wsHandler = WebSocketHandler()
        self.wsHandler.messageReceived.connect(self.onWsMessage)
        self.wsHandler.connected.connect(self.onWsConnected)
        self.wsHandler.disconnected.connect(self.onWsDisconnected)
        self.wsHandler.errorOccurred.connect(self.onWsError)
        
        # Delta tracking
        self.previousSegmentation = None
        self.baselineHash = None
        
        # IGT Link configuration
        self.igtlConnectorNode = None
        self.igtlServerPort = 18944
        self.useIGTLink = False  # Disabled for delta mode

    def connect(self, sessionId, token):
        """Connect to WebSocket server with session ID and token"""
        wsUrl = f"{self.WS_BASE_URL}/{sessionId}/ws?token={token}"
        print(f"Connecting to: {wsUrl}")
        self.wsHandler.connect(QUrl(wsUrl))
            

    def disconnect(self):
        """Disconnect from WebSocket"""
        self.connected = False

        self.wsHandler.disconnect()
        
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.previousSegmentation = None
        self.baselineHash = None

    def setSegmentationNode(self, node):
        """Set the segmentation node to monitor"""
        self.segmentationNode = node
        self.previousSegmentation = None
        self.baselineHash = None

    def setUserId(self, userId):
        """Set user ID for identification"""
        self.userId = userId

    def onWsOpen(self, ws):
        """Handle WebSocket connection opened"""
        print("WebSocket connection opened")
        self.connected = True
        
        # Request full segmentation state from server
        joinMessage = {
            "type": "join",
            "userId": self.userId,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        ws.send(json.dumps(joinMessage))

    def onWsMessage(self, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            msgType = data.get("type")
            print(f"Received message type: {msgType}")
            
            if msgType == "segmentation_delta":
                self.handleSegmentationDelta(data)
            elif msgType == "segmentation_full":
                self.handleFullSegmentation(data)
            elif msgType == "user_joined":
                print(f"User joined: {data.get('username')}")
                self.connectedUsers = data.get("totalUsers", 0)
            elif msgType == "user_list":
                self.connectedUsers = len(data.get("users", []))
            elif msgType == "user_left":
                print(f"User left: {data.get('username')}")
                self.connectedUsers = data.get("totalUsers", 0)
            elif msgType == "error":
                print(f"Server error: {data.get('message')}")
        except Exception as e:
            print(f"Error processing message: {str(e)}")

    def onWsError(self, ws, error):
        """Handle WebSocket errors"""
        print(f"WebSocket error: {error}")
        self.connected = False

    def onWsClose(self, ws, closeStatusCode, closeMsg):
        """Handle WebSocket connection closed"""
        print(f"WebSocket closed: {closeStatusCode} - {closeMsg}")
        self.connected = False

    def getCurrentSegmentationArray(self):
        """Get current segmentation as numpy array with segment ID mapping"""
        if not self.segmentationNode:
            return None, "No segmentation node available"
        
        try:
            labelmapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
                self.segmentationNode, labelmapNode
            )
            
            labelArray = slicer.util.arrayFromVolume(labelmapNode)
            dims = labelArray.shape
            
            spacing = list(labelmapNode.GetSpacing())
            origin = list(labelmapNode.GetOrigin())
            
            slicer.mrmlScene.RemoveNode(labelmapNode)
            
            segmentMapping = {}
            segmentation = self.segmentationNode.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                segmentId = segmentation.GetNthSegmentID(i)
                segmentName = segmentation.GetNthSegment(i).GetName()
                labelValue = i + 1
                segmentMapping[str(labelValue)] = segmentName
            
            presentLabels = [str(label) for label in np.unique(labelArray) if label > 0]
            filteredMapping = {k: segmentMapping[k] for k in presentLabels if k in segmentMapping}

        except Exception as e:
            return None, str(e)
        
        message = {
            'array': labelArray,  
            'dimensions': dims,
            'spacing': spacing,
            'origin': origin,
            'segmentNames': filteredMapping, 
            'dtype': str(labelArray.dtype)
        }

        print(message)

        return message, None

    def sendSegmentationDelta(self):
        """Send only the changed voxels since last update"""
        if self.isUpdating or not self.segmentationNode:
            return
        
        try:
            current, err = self.getCurrentSegmentationArray()
            if err is not None or current is None:
                print('error while converting to labelmapNode', e)
                return
            
            currentArray = current['array']
            
            if self.previousSegmentation is None:
                print("Sending initial full segmentation")
                self.sendFullSegmentation(current)
                self.previousSegmentation = currentArray.copy()
                return
            
            changedMask = currentArray != self.previousSegmentation
            
            if not np.any(changedMask):
                print("No changes detected, skipping update")
                return
            
            changedIndices = np.argwhere(changedMask)
            changedValues = currentArray[changedMask]
            
            numChanged = len(changedIndices)
            totalVoxels = currentArray.size
            changePercent = (numChanged / totalVoxels) * 100
            
            print(f"Changed voxels: {numChanged}/{totalVoxels} ({changePercent:.2f}%)")
            
            if changePercent > 30:
                print("Large change detected, sending full segmentation")
                self.sendFullSegmentation(current)
                self.previousSegmentation = currentArray.copy()
                return
            
            import zlib
            
            indicesBytes = changedIndices.astype(np.uint16).tobytes()
            valuesBytes = changedValues.tobytes()
            
            compressedIndices = zlib.compress(indicesBytes)
            compressedValues = zlib.compress(valuesBytes)
            
            encodedIndices = base64.b64encode(compressedIndices).decode('utf-8')
            encodedValues = base64.b64encode(compressedValues).decode('utf-8')
            
            message = {
                "type": "segmentation_delta",
                "userId": self.userId,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "indices": encodedIndices,
                    "values": encodedValues,
                    "numChanges": numChanged,
                    "dimensions": current['dimensions'],
                    "spacing": current['spacing'],
                    "origin": current['origin'],
                    "dataType": current['dtype']
                }
            }
            
            if self.ws and self.connected:
                self.ws.send(json.dumps(message))
                self.sentCount += 1
                print(f"Sent delta update #{self.sentCount} ({numChanged} voxels)")
            
            # Update previous state
            self.previousSegmentation = currentArray.copy()
            
        except Exception as e:
            print(f"ERROR sending delta: {str(e)}")
            import traceback
            traceback.print_exc()

    def sendFullSegmentation(self, current):
        """Send full segmentation (used for initial sync or large changes)"""
        try:
            import zlib
            compressor = zlib.compressobj(
                level=zlib.Z_DEFAULT_COMPRESSION, 
                method=zlib.DEFLATED, 
                wbits=15, 
                memLevel=8, 
                strategy=zlib.Z_RLE
            )
            compressedData = compressor.compress(current['array'].tobytes())
            compressedData += compressor.flush()
            encodedData = base64.b64encode(compressedData).decode('utf-8')
            
            message = {
                "type": "segmentation_full",
                "userId": self.userId,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "imageData": encodedData,
                    "dimensions": current['dimensions'],
                    "spacing": current['spacing'],
                    "origin": current['origin'],
                    "dataType": current['dtype']
                }
            }
            
            if self.ws and self.connected:
                self.ws.send(json.dumps(message))
                self.sentCount += 1
                print(f"Sent full segmentation #{self.sentCount}")
                
        except Exception as e:
            print(f"ERROR sending full segmentation: {str(e)}")
            import traceback
            traceback.print_exc()

    def handleSegmentationDelta(self, data):
        """Handle incoming delta update"""
        print('in handling delta')
        if not self.segmentationNode or self.isUpdating:
            return

        if data.get("userId") == self.userId:
            return

        try:
            self.isUpdating = True
            deltaData = data.get("data", {})
            
            import zlib
            
            compressedIndices = base64.b64decode(deltaData["indices"])
            compressedValues = base64.b64decode(deltaData["values"])
            
            indicesBytes = zlib.decompress(compressedIndices)
            valuesBytes = zlib.decompress(compressedValues)
            
            indices = np.frombuffer(indicesBytes, dtype=np.uint16).reshape(-1, 3)
            values = np.frombuffer(valuesBytes, dtype=deltaData["dataType"])
            
            current = self.getCurrentSegmentationArray()
            if current is None:
                print("No current segmentation to apply delta to")
                return
            
            currentArray = current['array']
            for idx, value in zip(indices, values):
                currentArray[idx[0], idx[1], idx[2]] = value
            
            self.updateSegmentationFromArray(currentArray, current)
            
            self.receivedCount += 1
            print(f"Applied delta update #{self.receivedCount} from {data.get('userId')} ({len(values)} voxels)")
            
            self.previousSegmentation = currentArray.copy()
            
        except Exception as e:
            print(f"Error applying delta: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.isUpdating = False

    def handleFullSegmentation(self, message):
        """Handle incoming full segmentation"""

        print('recieved incoming segmentation')
        # if not self.segmentationNode or self.isUpdating:
        #     return

        if message.get("userId") == self.userId:
            return

        try:
            self.isUpdating = True
            data = message.get("data", {})
            print('dtype: ', data.get("dataType"))
            
            import zlib
            encodedData = data.get("imageData")
            compressedData = base64.b64decode(encodedData)
            decompressedData = zlib.decompress(compressedData)
            
            dims = data.get("dimensions")
            dataType = data.get("dataType")
            print('decompression done')
            arrayData = np.frombuffer(decompressedData, dtype=dataType)
            arrayData = arrayData.reshape(dims[2], dims[1], dims[0])

            labelmapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            labelmapNode.SetSpacing(data['spacing'])
            labelmapNode.SetSpacing(data['origin'])

            slicer.util.updateVolumeFromArray(labelmapNode, arrayData)

            segmentEditor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            segmentationNode = segmentEditor.segmentationNode()

            if segmentationNode is not None:
                print("No segmentation node in editor - creating new one")
                segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                segmentEditor.setSegmentationNode(segmentationNode)
            
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmapNode, 
                segmentationNode
            )

            print('import done')
            
            #self.updateSegmentNames(segmentationNode, data['segmentNames'])
            
            slicer.mrmlScene.RemoveNode(labelmapNode)
            
            #segmentationNode.InvokeCustomModifiedEvent(slicer.vtkMRMLSegmentationNode.Modified)
            
            #self.updateSegmentationFromArray(arrayData, updateData)
            
            self.receivedCount += 1
            print(f"Applied full segmentation #{self.receivedCount} from {message.get('userId')}")
            
            self.previousSegmentation = arrayData.copy()
            
        except Exception as e:
            print(f"Error applying full segmentation: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.isUpdating = False

    def updateSegmentationFromArray(self, arrayData, metadata):
        """Update segmentation node from numpy array"""
        labelmapNode = slicer.vtkMRMLLabelMapVolumeNode()
        slicer.mrmlScene.AddNode(labelmapNode)
        
        from vtk.util import numpy_support
        vtkArray = numpy_support.numpy_to_vtk(arrayData.ravel(), deep=True)
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(metadata["dimensions"])
        imageData.GetPointData().SetScalars(vtkArray)
        labelmapNode.SetAndObserveImageData(imageData)
        labelmapNode.SetSpacing(metadata["spacing"])
        labelmapNode.SetOrigin(metadata["origin"])
        
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelmapNode, self.segmentationNode
        )
        
        slicer.mrmlScene.RemoveNode(labelmapNode)

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

