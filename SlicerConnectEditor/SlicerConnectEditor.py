import os
import vtk
from vtk.util import numpy_support
import vtkSegmentationCorePython as vtkSegmentationCore
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import numpy as np
import json
import base64
import hashlib
from datetime import datetime, timezone
import websocket

class SlicerConnectEditor(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerConnectEditor"
        self.parent.categories = ["None"]
        self.parent.dependencies = []
        self.parent.contributors = ["Piyush Khurana"]
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

        self.logic._nodeUpdatedCallbacks.append(self.onExternalNodeUpdate)

        uiWidget = slicer.util.loadUI(self.resourcePath('UI/SlicerConnectEditor.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.refreshConnectionButton.clicked.connect(self.checkAndConnectFromSession)

        self.logic.wsHandler.socketConnected.connect(self.onConnected)
        self.logic.wsHandler.socketDisconnected.connect(self.onDisconnected)
        self.setupSegmentEditor()

        self._syncSegmentationNode()
        
        self.checkAndConnectFromSession()
        self.user_info = slicer.app.settings().value("SlicerConnectUser")


    def onExternalNodeUpdate(self, node):
        """Called when Logic receives a full segmentation from the server"""
        if self.segment_editor_node and node:
            self.segment_editor_node.SetAndObserveSegmentationNode(node)
            self.onSegmentationSelected(node)

    def _syncSegmentationNode(self):
        """Force re-sync segmentation node after reload."""
        if self.segment_editor_node:
            currentNode = self.segment_editor_node.GetSegmentationNode()
            if currentNode:
                print(f"Re-syncing segmentation node after reload: {currentNode.GetName()}")
                self.onSegmentationSelected(currentNode)

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
            slicer.util.selectModule("SlicerConnect")

    def connectToSession(self, sessionId):
        """Connect to a specific session"""
        self.sessionId = sessionId
        
        token = slicer.app.settings().value('SlicerConnectToken')
        if not token:
            self.promptLogin()
            return

        self.addLog(f"Connecting to session {sessionId}...")
        self.logic.connect(sessionId, token)
        
    def onConnected(self):
        self.ui.statusLabel.setText(f"Connected to Session {self.sessionId}")
        #add observers

    def onDisconnected(self):
        self.ui.statusLabel.setText("Connection Failed")

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
        if self.logic.wsHandler.isConnected() and not self.logic.isUpdating:
            qt.QTimer.singleShot(50, self._debouncedSend)

    def _debouncedSend(self):
        if not self.logic.isUpdating:
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
            self.logic.closeConnection()

    def resourcePath(self, filename):
        """Get path to resource file"""
        scriptedModulesPath = os.path.dirname(slicer.util.modulePath(self.moduleName))
        return os.path.join(scriptedModulesPath, 'Resources', filename)


class WebSocketHandler(qt.QObject):
    messageReceived = qt.Signal(str)
    socketConnected = qt.Signal()
    socketDisconnected = qt.Signal()
    errorOccurred = qt.Signal(str)

    POLL_INTERVAL_MS = 200

    def __init__(self):
        super().__init__()
        self.ws = None
        self._isConnected = False
        self._timer = qt.QTimer()
        self._timer.timeout.connect(self._poll)
        self._pingTimer = qt.QTimer()
        self._pingTimer.setInterval(5000)
        self._pingTimer.timeout.connect(self._sendPing)

    def connectToServer(self, url):
        self.ws = websocket.WebSocket()
        try:
            self.ws.connect(url)
            self.ws.sock.setblocking(False) 
            self._isConnected = True
            self._timer.start(self.POLL_INTERVAL_MS)
            self._pingTimer.start()
            self.socketConnected.emit()
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def _sendPing(self):
        if self.ws and self._isConnected:
            try:
                message={"type": "ping"} 
                self.ws.send(json.dumps(message))
            except Exception as e:
                self.errorOccurred.emit(str(e))

    def _poll(self):
        """Called by QTimer every POLL_INTERVAL_MS to check for incoming messages."""
        if not self.ws or not self._isConnected:
            return
        try:
            message = self.ws.recv()
            if message:
                self.messageReceived.emit(message)
        except websocket.WebSocketConnectionClosedException:
            self._handleDisconnect()
        except BlockingIOError:
            pass  
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def _handleDisconnect(self):
        self._isConnected = False
        self._timer.stop()
        self._pingTimer.stop()
        self.socketDisconnected.emit()

    def send(self, message):
        if self.ws and self._isConnected:
            try:
                self.ws.send(message)
            except Exception as e:
                self.errorOccurred.emit(str(e))

    def isConnected(self):
        return self._isConnected

    def closeConnection(self):
        self._timer.stop()
        self._pingTimer.stop()
        if self.ws:
            self.ws.shutdown()
            self.ws = None
        self._handleDisconnect()

class SlicerConnectEditorLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.WS_BASE_URL = "ws://slicerconnect.from-delhi.net/collaboration/sessions"

        self._nodeUpdatedCallbacks = []
        self.segmentationNode = None
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.isUpdating = False
        self.wsHandler = WebSocketHandler()
        self.wsHandler.messageReceived.connect(self.onWsMessage)
        self.wsHandler.socketConnected.connect(self.onWsConnected)
        self.wsHandler.socketDisconnected.connect(self.onWsDisconnected)
        self.wsHandler.errorOccurred.connect(self.onWsError)
        
        self.previousSegmentation = None
        self.baselineHash = None

        self._masterLabelmapNode = None

    def _emitNodeUpdated(self, node):
        for cb in self._nodeUpdatedCallbacks:
            cb(node)

    def connect(self, sessionId, token):
        """Connect to WebSocket server with session ID and token"""
        wsUrl = f"{self.WS_BASE_URL}/{sessionId}/ws?token={token}"
        print(f"Connecting to: {wsUrl}")
        self.wsHandler.connectToServer(wsUrl)

    def handleDisconnect(self):
        """Disconnect from WebSocket"""
        self.wsHandler.closeConnection()
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.previousSegmentation = None

        if self._masterLabelmapNode:
            slicer.mrmlScene.RemoveNode(self._masterLabelmapNode)
            self._masterLabelmapNode = None

        self.baselineHash = None

    def closeConnection(self):
        self.wsHandler.closeConnection()

    def setSegmentationNode(self, node):
        """Set the segmentation node to monitor"""
        self.segmentationNode = node
        self.previousSegmentation = None
        self.baselineHash = None

    def onWsConnected(self):
        """Handle WebSocket connection opened"""
        print("WebSocket connection opened")
        joinMessage = {
            "type": "join",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.wsHandler.send(json.dumps(joinMessage))

    def onWsMessage(self, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            incomingHash = data.get("sessionHash")
            msgType = data.get("type")
            if msgType == "segmentation_delta":
                print('received delta seg')
                self.handleSegmentationDelta(data)
            elif msgType == "segmentation_full":
                print("ReceivedSegmentation")
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

    def onWsError(self, error):
        """Handle WebSocket errors"""
        print(f"WebSocket error: {error}")

    def onWsDisconnected(self):
        """Handle WebSocket connection closed"""
        print(f"WebSocket closed:")

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
            shape = labelArray.shape
            dims = [shape[2], shape[1], shape[0]]
            
            spacing = list(labelmapNode.GetSpacing())
            origin = list(labelmapNode.GetOrigin())
            matrix = vtk.vtkMatrix4x4()
            labelmapNode.GetIJKToRASMatrix(matrix)
            direction = []
            for row in range(4):
                for col in range(4):
                    direction.append(matrix.GetElement(row, col))
            
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
            'direction': direction,
            'dtype': str(labelArray.dtype)
        }

        return message, None


    def _shouldUpdate(self, incomingHash):
        if not self.baselineHash: 
            return True
        if not incomingHash or incomingHash == self.baselineHash:
            return False
        return True
        

    def _resampleToShape(self, array, targetShape):
        """Dependency-free nearest neighbour resize using numpy indexing."""
        iz = np.round(np.linspace(0, array.shape[0] - 1, targetShape[0])).astype(int)
        iy = np.round(np.linspace(0, array.shape[1] - 1, targetShape[1])).astype(int)
        ix = np.round(np.linspace(0, array.shape[2] - 1, targetShape[2])).astype(int)
        return array[np.ix_(iz, iy, ix)]

    def _computeChangedMask(self, currentArray):
        """Compare current segmentation to previous, handling shape mismatches."""
        if self.previousSegmentation is None:
            return np.ones(currentArray.shape, dtype=bool)

        prev = self.previousSegmentation

        if currentArray.shape != prev.shape:
            print(f"Shape mismatch: current={currentArray.shape} prev={prev.shape} — resampling")
            prev = self._resampleToShape(prev, currentArray.shape)

        return currentArray != prev


    def sendSegmentationDelta(self):
        """Send only the changed voxels since last update"""
        if self.isUpdating or not self.segmentationNode:
            return

        try:
            current, err = self.getCurrentSegmentationArray()
            if err is not None or current is None:
                print(f"Error while converting to labelmapNode: {err}")  
                return

            currentArray = current['array']

            if self.previousSegmentation is None:
                print("Sending initial full segmentation")
                self.sendFullSegmentation(current)
                self.previousSegmentation = currentArray.copy()
                return

            changedMask = self._computeChangedMask(currentArray)  

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

            self.baselineHash = hashlib.sha256(current['array'].tobytes()).hexdigest()
            
            message = {
                "type": "segmentation_delta",
                "sessionHash": self.baselineHash,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "indices": encodedIndices,
                    "values": encodedValues,
                    "numChanges": numChanged,
                    "dimensions": current['dimensions'],
                    "spacing": current['spacing'],
                    "direction": current['direction'],
                    "origin": current['origin'],
                    "dataType": current['dtype']
                }
            }
            
            if self.wsHandler and self.wsHandler.isConnected():
                self.wsHandler.send(json.dumps(message))
                self.sentCount += 1
                print(f"Sent delta update #{self.sentCount} ({numChanged} voxels)")
            
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

            self.baselineHash = hashlib.sha256(current['array'].tobytes()).hexdigest()
            print('direction: ', current['direction'])
            
            message = {
                "type": "segmentation_full",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sessionHash": self.baselineHash,
                "data": {
                    "imageData": encodedData,
                    "dimensions": current['dimensions'],
                    "spacing": current['spacing'],
                    "origin": current['origin'],
                    "direction": current['direction'],
                    "dataType": current['dtype']
                }
            }
            
            if self.wsHandler and self.wsHandler.isConnected():
                self.wsHandler.send(json.dumps(message))
                self.sentCount += 1
                print(f"Sent full segmentation #{self.sentCount}")
                
        except Exception as e:
            print(f"ERROR sending full segmentation: {str(e)}")
            import traceback
            traceback.print_exc()


    def handleSegmentationDelta(self, data):
        """Handle incoming delta update with coordinate safety"""
        if not self.segmentationNode or self.isUpdating:
            return

        try:
            self.isUpdating = True
            deltaData = data.get("data", {})

            import zlib
            import base64

            compressedIndices = base64.b64decode(deltaData["indices"])
            compressedValues = base64.b64decode(deltaData["values"])
            indicesBytes = zlib.decompress(compressedIndices)
            valuesBytes = zlib.decompress(compressedValues)

            indices = np.frombuffer(indicesBytes, dtype=np.uint16).reshape(-1, 3)
            values = np.frombuffer(valuesBytes, dtype=deltaData["dataType"])

            labelmapNode = self._getOrCreateMasterLabelmap(deltaData)
            currentArray = slicer.util.arrayFromVolume(labelmapNode)

            incomingDims = deltaData.get("dimensions") # [X, Y, Z]
            print('incoming dims: ', incomingDims)
            #currentShape = currentArray.shape          # (Z, Y, X)
            
            # if incomingDims[0] != currentShape[2] or incomingDims[1] != currentShape[1]:
            #     scaleZ = currentShape[0] / incomingDims[2]
            #     scaleY = currentShape[1] / incomingDims[1]
            #     scaleX = currentShape[2] / incomingDims[0]
            #     
            #     indices = indices.astype(np.float32)
            #     indices[:, 0] = np.clip(np.round(indices[:, 0] * scaleZ), 0, currentShape[0] - 1)
            #     indices[:, 1] = np.clip(np.round(indices[:, 1] * scaleY), 0, currentShape[1] - 1)
            #     indices[:, 2] = np.clip(np.round(indices[:, 2] * scaleX), 0, currentShape[2] - 1)
            #     indices = indices.astype(np.uint16)

            currentArray[indices[:, 0], indices[:, 1], indices[:, 2]] = values

            slicer.util.updateVolumeFromArray(labelmapNode, currentArray)
            
            self._applyArrayToSegmentation(currentArray, deltaData)

        except Exception as e:
            print(f"Delta Error: {e}")
        finally:
            self.isUpdating = False

    def _getOrCreateSegmentationNode(self):
        nodeName = "CollaborativeSegmentation"
        node = slicer.mrmlScene.GetFirstNodeByName(nodeName)
        
        if not node:
            # Check if any segmentation node exists to adopt it
            node = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
            if node:
                node.SetName(nodeName)
            else:
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", nodeName)
                
        return node

    def _applyArrayToSegmentation(self, arrayData, metadata):
        """
        Update segmentation in place using direct VTK Logic calls.
        Bypasses slicer.util helpers to avoid 'AttributeError' and geometry shifts.
        """
        segmentationNode = None
        try:
            segmentationNode = self._getOrCreateSegmentationNode()
            segmentationNode.DisableModifiedEventOn()
            
            segmentation = segmentationNode.GetSegmentation()
            labelmapNode = self._getOrCreateMasterLabelmap(metadata)

            uniqueLabels = sorted([int(l) for l in np.unique(arrayData) if l > 0])

            if segmentation.GetNumberOfSegments() == 0:
                segmentationNode.SetNodeReferenceID(
                    "ReferenceImageGeometry", 
                    labelmapNode.GetID()
                )
                slicer.util.updateVolumeFromArray(labelmapNode, arrayData)
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    labelmapNode, segmentationNode
                )
                return

            spacing = labelmapNode.GetSpacing()
            origin = labelmapNode.GetOrigin()
            dirMatrix = vtk.vtkMatrix4x4()
            labelmapNode.GetIJKToRASMatrix(dirMatrix)

            existingSegmentIds = [segmentation.GetNthSegmentID(i) for i in range(segmentation.GetNumberOfSegments())]
            updatedSegmentIds = []

            for labelValue in uniqueLabels:
                segmentIndex = labelValue - 1
                
                if segmentIndex >= segmentation.GetNumberOfSegments():
                    segmentId = segmentation.AddEmptySegment(f"Segment_{labelValue}")
                else:
                    segmentId = segmentation.GetNthSegmentID(segmentIndex)
                
                updatedSegmentIds.append(segmentId)
                binaryMask = (arrayData == labelValue).astype(np.uint8)
                shape = binaryMask.shape # (Z, Y, X)
                
                orientedMask = vtkSegmentationCore.vtkOrientedImageData()
                
                orientedMask.SetExtent(0, shape[2]-1, 0, shape[1]-1, 0, shape[0]-1)
                orientedMask.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)

                vtkArray = numpy_support.numpy_to_vtk(binaryMask.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
                orientedMask.GetPointData().SetScalars(vtkArray)

                orientedMask.SetSpacing(spacing)
                orientedMask.SetOrigin(origin)
                orientedMask.SetDirectionMatrix(dirMatrix)

                slicer.modules.segmentations.logic().SetBinaryLabelmapToSegment(
                    orientedMask, 
                    segmentationNode, 
                    segmentId,
                    0 # vtkSegmentation.EXTENT_UNION
                )

            for segId in existingSegmentIds:
                if segId not in updatedSegmentIds:
                    emptyMask = vtkSegmentationCore.vtkOrientedImageData()
                    emptyMask.SetSpacing(spacing)
                    emptyMask.SetOrigin(origin)
                    emptyMask.SetDirectionMatrix(dirMatrix)
                    
                    slicer.modules.segmentations.logic().SetBinaryLabelmapToSegment(
                        emptyMask, segmentationNode, segId, 0
                    )


        except Exception as e:
            print(f"Error in _applyArrayToSegmentation: {str(e)}")
            import traceback
            traceback.print_exc()

        finally:
            if segmentationNode is not None:
                segmentationNode.DisableModifiedEventOff()
                segmentationNode.Modified()

    def handleFullSegmentation(self, message):
        if self.isUpdating:
            return

        segmentationNode = None
        try:
            self.isUpdating = True
            data = message.get("data", {})
            incomingHash = message.get("sessionHash")

            if not self._shouldUpdate(incomingHash):
                print('hash matched')
                return

            import zlib
            import base64

            encodedData = data.get("imageData")
            if not encodedData:
                return

            compressedData = base64.b64decode(encodedData)
            decompressedData = zlib.decompress(compressedData)

            dims = data.get("dimensions")
            dataType = data.get("dataType")
            direction = data.get("direction")

            print('recieved')
            print('dims', dims)

            
            m = vtk.vtkMatrix4x4()
            for i in range(16):
                m.SetElement(i // 4, i % 4, direction[i])

            if not dims or not dataType:
                return

            arrayData = np.frombuffer(decompressedData, dtype=dataType)
            arrayData = arrayData.reshape(dims[2], dims[1], dims[0])
            
            labelmapNode = self._getOrCreateMasterLabelmap(data)
            slicer.util.updateVolumeFromArray(labelmapNode, arrayData)

            segmentationNode = self._getOrCreateSegmentationNode()
            print("created or found segNode")

            segmentationNode.DisableModifiedEventOn()
            segmentationNode.GetSegmentation().RemoveAllSegments()

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmapNode,
                segmentationNode
            )
            print(f"Applied full segmentation #{self.receivedCount} from {message.get('username')}")

            self.previousSegmentation = arrayData.copy()
            self.receivedCount += 1
            self._emitNodeUpdated(segmentationNode)

            if incomingHash:
                self.baselineHash = incomingHash

        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            if segmentationNode is not None:
                segmentationNode.DisableModifiedEventOff()
                segmentationNode.Modified()

            self.isUpdating = False


    def _getOrCreateMasterLabelmap(self, metadata):
        nodeName = 'CollabLabelMap'
        
        # 1. Try internal reference first
        if self._masterLabelmapNode is not None:
            return self._masterLabelmapNode

        # 2. Search scene for the node by name
        self._masterLabelmapNode = slicer.mrmlScene.GetFirstNodeByName(nodeName)

        # 3. If not found by name, check classes (robust check for renamed nodes)
        if not self._masterLabelmapNode:
            nodes = slicer.mrmlScene.GetNodesByClass('vtkMRMLLabelMapVolumeNode')
            for i in range(nodes.GetNumberOfItems()):
                # FIX: Use GetItemAsObject instead of GetItemAsVTKObject
                node = nodes.GetItemAsObject(i)
                if nodeName in node.GetName():
                    self._masterLabelmapNode = node
                    break

        # 4. Create if it still doesn't exist
        if not self._masterLabelmapNode:
            self._masterLabelmapNode = slicer.mrmlScene.AddNewNodeByClass(
                'vtkMRMLLabelMapVolumeNode', nodeName
            )
            # Hide from the data tree and Subject Hierarchy
            self._masterLabelmapNode.SetHideFromEditors(True)
            
            dims = metadata.get('dimensions', [256, 256, 256])
            import numpy as np
            emptyArray = np.zeros((dims[2], dims[1], dims[0]), dtype=np.uint8)
            slicer.util.updateVolumeFromArray(self._masterLabelmapNode, emptyArray)

        # 5. Sync Geometry
        self._masterLabelmapNode.SetSpacing(*metadata['spacing'])
        self._masterLabelmapNode.SetOrigin(*metadata['origin'])
        if 'direction' in metadata and len(metadata['direction']) == 16:
            m = vtk.vtkMatrix4x4()
            for i in range(16):
                m.SetElement(i // 4, i % 4, metadata['direction'][i])
            self._masterLabelmapNode.SetIJKToRASMatrix(m)
                
        return self._masterLabelmapNode

    def _setEditorSegmentationNode(self, segmentationNode):
        """Set the segmentation node in the Segment Editor if it's open."""
        try:
            segmentEditor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            segmentEditor.setSegmentationNode(segmentationNode)
        except Exception:
            pass  

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

