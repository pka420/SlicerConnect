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
import websocket

class SlicerConnectEditor(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "SlicerConnectEditor"
        self.parent.categories = ["None"]
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

        self.logic.wsHandler.socketConnected.connect(self.onConnected)
        self.logic.wsHandler.socketDisconnected.connect(self.onDisconnected)
        self.setupSegmentEditor()

        self._syncSegmentationNode()
        
        self.checkAndConnectFromSession()
        self.user_info = slicer.app.settings().value("SlicerConnectUser")

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
            slicer.util.selectModule("CollaborativeSegmentation")

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
        if self.logic.wsHandler.isConnected and not self.logic.isUpdating:
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

    POLL_INTERVAL_MS = 50  

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
        print('sending ping')
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
        self.segmentationNode = None
        self.sentCount = 0
        self.receivedCount = 0
        self.connectedUsers = 0
        self.isUpdating = False
        self.WS_BASE_URL = "ws://localhost:8000/collaboration/sessions"

        self.wsHandler = WebSocketHandler()
        self.wsHandler.messageReceived.connect(self.onWsMessage)
        self.wsHandler.socketConnected.connect(self.onWsConnected)
        self.wsHandler.socketDisconnected.connect(self.onWsDisconnected)
        self.wsHandler.errorOccurred.connect(self.onWsError)
        
        self.previousSegmentation = None
        self.baselineHash = None

        self._masterLabelmapNode = None

        self._debounceTimer = qt.QTimer()
        self._debounceTimer.setSingleShot(True)
        self._debounceTimer.setInterval(2000)
        self._debounceTimer.timeout.connect(self._sendDebouncedDelta)
        
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

        return message, None

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

    def _sendDebouncedDelta(self):
        print('sending delta')

    def sendSegmentationDelta(self):
        """Send only the changed voxels since last update"""
        self._debounceTimer.start()
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
            
            message = {
                "type": "segmentation_delta",
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
            
            if self.wsHandler and self.wsHandler.isConnected:
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
            
            message = {
                "type": "segmentation_full",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "imageData": encodedData,
                    "dimensions": current['dimensions'],
                    "spacing": current['spacing'],
                    "origin": current['origin'],
                    "dataType": current['dtype']
                }
            }
            
            if self.wsHandler and self.wsHandler.isConnected:
                self.wsHandler.send(json.dumps(message))
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

            current, err = self.getCurrentSegmentationArray()
            if err is not None or current is None:
                print(f"Error getting segmentation: {err}")
                return

            currentArray = current['array'].copy() 

            incomingDims = tuple(deltaData.get("dimensions", []))  
            if incomingDims and incomingDims != currentArray.shape:
                print(f"Delta shape mismatch: incoming={incomingDims} current={currentArray.shape} — remapping indices")
                scaleZ = currentArray.shape[0] / incomingDims[0]
                scaleY = currentArray.shape[1] / incomingDims[1]
                scaleX = currentArray.shape[2] / incomingDims[2]

                indices = indices.astype(np.float32)
                indices[:, 0] = np.clip(np.round(indices[:, 0] * scaleZ), 0, currentArray.shape[0] - 1)
                indices[:, 1] = np.clip(np.round(indices[:, 1] * scaleY), 0, currentArray.shape[1] - 1)
                indices[:, 2] = np.clip(np.round(indices[:, 2] * scaleX), 0, currentArray.shape[2] - 1)
                indices = indices.astype(np.uint16)

            currentArray[indices[:, 0], indices[:, 1], indices[:, 2]] = values

            self._applyArrayToSegmentation(currentArray, current)

            self.previousSegmentation = currentArray.copy()
            self.receivedCount += 1
            print(f"Applied delta #{self.receivedCount} from {data.get('username')} ({len(values)} voxels)")

        except KeyError as e:
            print(f"Missing field in delta data: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            print(f"Error applying delta: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.isUpdating = False

    def _getOrCreateMasterLabelmap(self, metadata):
        """Reuse the same labelmap node across updates to avoid creating/deleting nodes."""
        if self._masterLabelmapNode is None or not slicer.mrmlScene.GetNodeByID(
            self._masterLabelmapNode.GetID()
        ):
            self._masterLabelmapNode = slicer.mrmlScene.AddNewNodeByClass(
                'vtkMRMLLabelMapVolumeNode', 'CollabLabelMap'
            )
        self._masterLabelmapNode.SetSpacing(*metadata['spacing'])
        self._masterLabelmapNode.SetOrigin(*metadata['origin'])
        return self._masterLabelmapNode

    def _applyArrayToSegmentation(self, arrayData, metadata):
        """
        Update segmentation in place using slicer's built-in per-segment update.
        No import, no new segments, changes reflect immediately on screen.
        """
        try:
            segmentationNode = self._getOrCreateSegmentationNode()
            segmentation = segmentationNode.GetSegmentation()

            uniqueLabels = sorted([int(l) for l in np.unique(arrayData) if l > 0])

            # --- first time: bootstrap segments if none exist ---
            if segmentation.GetNumberOfSegments() == 0:
                labelmapNode = self._getOrCreateMasterLabelmap(metadata)
                slicer.util.updateVolumeFromArray(labelmapNode, arrayData)
                slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                    labelmapNode, segmentationNode
                )
                print(f"Bootstrapped {segmentation.GetNumberOfSegments()} segments")
                return

            # --- subsequent updates: update each segment's mask directly ---
            # disable modified events during bulk update to avoid re-renders mid-update
            wasModified = segmentationNode.StartModify()

            for labelValue in uniqueLabels:
                segmentIndex = labelValue - 1

                # create segment if label has no corresponding segment yet
                if segmentIndex >= segmentation.GetNumberOfSegments():
                    newSegmentId = segmentation.AddEmptySegment(f"Segment_{labelValue}")
                    print(f"Added new segment for label {labelValue}: {newSegmentId}")

                segmentId = segmentation.GetNthSegmentID(segmentIndex)

                # extract binary mask for this label
                binaryMask = (arrayData == labelValue).astype(np.uint8)

                # this is the key call — updates the segment's voxels directly
                slicer.util.updateSegmentBinaryLabelmapFromArray(
                    binaryMask,
                    segmentId,
                    segmentationNode
                )

            # handle segments that no longer have any voxels
            for i in range(segmentation.GetNumberOfSegments()):
                segmentId = segmentation.GetNthSegmentID(i)
                labelValue = i + 1
                if labelValue not in uniqueLabels:
                    # clear this segment — fill with zeros
                    binaryMask = np.zeros(arrayData.shape, dtype=np.uint8)
                    slicer.util.updateSegmentBinaryLabelmapFromArray(
                        binaryMask,
                        segmentId,
                        segmentationNode
                    )

            # re-enable events and fire a single Modified — triggers one render
            segmentationNode.EndModify(wasModified)

        except Exception as e:
            print(f"Error in _applyArrayToSegmentation: {str(e)}")
            import traceback
            traceback.print_exc()
        
    def handleFullSegmentation(self, message):
        """Handle incoming full segmentation"""
        if self.isUpdating:
            return

        try:
            self.isUpdating = True
            data = message.get("data", {})

            import zlib
            import base64

            encodedData = data.get("imageData")
            if not encodedData:
                print("No imageData in message")
                return

            compressedData = base64.b64decode(encodedData)
            decompressedData = zlib.decompress(compressedData)

            dims = data.get("dimensions")
            dataType = data.get("dataType")

            if not dims or not dataType:
                print("Missing dimensions or dataType")
                return

            arrayData = np.frombuffer(decompressedData, dtype=dataType)
            arrayData = arrayData.reshape(dims[2], dims[1], dims[0])

            labelmapNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode', 'TempLabelMap')
            labelmapNode.SetSpacing(data['spacing'])
            labelmapNode.SetOrigin(data['origin'])
            slicer.util.updateVolumeFromArray(labelmapNode, arrayData)

            segmentationNode = self._getOrCreateSegmentationNode()

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmapNode,
                segmentationNode
            )
            print('import done')

            slicer.mrmlScene.RemoveNode(labelmapNode)
            segmentationNode.Modified()

            self.previousSegmentation = arrayData.copy()
            self.receivedCount += 1
            print(f"Applied full segmentation #{self.receivedCount} from {message.get('username')}")

        except KeyError as e:
            print(f"Missing required field in segmentation data: {e}")
            import traceback
            traceback.print_exc()
        except zlib.error as e:
            print(f"Decompression failed: {e}")
        except Exception as e:
            print(f"Error applying full segmentation: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.isUpdating = False


    def _getOrCreateSegmentationNode(self):
        """
        Returns a segmentation node in this priority order:
        1. Node currently selected in Segment Editor
        2. First segmentation node found in the scene
        3. Newly created segmentation node
        """
        try:
            segmentEditor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
            segmentationNode = segmentEditor.segmentationNode()
            if segmentationNode is not None:
                print(f"Using segmentation from editor: {segmentationNode.GetName()}")
                return segmentationNode
        except Exception:
            pass  

        segmentationNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
        if segmentationNode is not None:
            print(f"Using existing segmentation from scene: {segmentationNode.GetName()}")
            self._setEditorSegmentationNode(segmentationNode)
            return segmentationNode

        print("No segmentation node found — creating new one")
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", "ReceivedSegmentation"
        )
        self._setEditorSegmentationNode(segmentationNode)
        return segmentationNode


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

