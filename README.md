# SlicerConnect: Real-Time Collaborative Segmentation
SlicerConnect is a 3D Slicer extension designed to enable "Google Docs-style" collaboration for medical image segmentation. 
It allows multiple researchers or clinicians to work on the same segmentation simultaneously, synchronizing edits in real-time across different locations.

## Extension Structure
The extension consists of three specialized modules that manage the lifecycle of a collaborative session:

##Login:

Handles secure user authentication.

Exchanges credentials for a session token from the central server.

Ensures encrypted communication for all subsequent steps.

CollaborativeSegmentation:

The Project Hub of the extension.

Implements Role-Based Access Control (RBAC) to manage user permissions.

Displays available projects and active collaborators.

Handles the initial download/sync of the volume data.

SlicerConnectEditor:

The Real-Time Engine.

Hooks directly into Slicer's Segment Editor.

Broadcats local voxel changes (deltas) and applies incoming edits from remote users.

Optimized with zlib compression and debounced updates for smooth performance.

## Installation & Setup
Prerequisites
3D Slicer (Stable or Preview).

Python Dependencies: numpy, websockets, and requests (installed via Slicer's Python console if not present).

Backend Server: A running SlicerConnect WebSocket/API server.

Installation
Clone this repository to your local machine:

```
git clone https://github.com/your-repo/SlicerConnect.git
```

Open 3D Slicer.

Navigate to Edit -> Application Settings -> Modules.

Click Add and select the root SlicerConnect folder.

Restart Slicer to initialize the modules.

## Testing on a Single Computer
You can test the full collaborative experience on a single Linux machine by launching two isolated Slicer instances.

1. Launch Instance A (User 1)
Open a terminal and run:

# Point this to your Slicer executable and the extension path
```
./Slicer --settings-disabled --additional-module-paths /path/to/SlicerConnect/
```
Go to Login, sign in as User_A.

In CollaborativeSegmentation, select a project and enter Edit Mode.

2. Launch Instance B (User 2)
Open a second terminal and run the same command:

```
./Slicer --settings-disabled --additional-module-paths /path/to/SlicerConnect/
```
Log in as User_B and join the same project.

3. Verify Synchronization
Place the two Slicer windows side-by-side.

Pick a tool (e.g., Paint) in Instance A and draw on a slice.

The segmentation should appear in Instance B after a brief transmission delay.

Note: Using the --settings-disabled flag is essential for local testing. It prevents both instances from trying to write to the same .ini file simultaneously, which causes crashes.

## Architecture Highlights
Voxel Delta Sync: Instead of sending full volumes, SlicerConnect only transmits changed voxels to save bandwidth.

Stateful Recovery: The server maintains the "Source of Truth," allowing new users to join an ongoing session and receive the current state immediately.

Event Guarding: Prevents "Echo Loops" by distinguishing between local user edits and incoming remote updates.
