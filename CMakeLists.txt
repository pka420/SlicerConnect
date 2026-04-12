cmake_minimum_required(VERSION 3.16.3)

project(SlicerConnect)
#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/SlicerConnect")
set(EXTENSION_CONTRIBUTORS "Piyush Khurana (Aryabhatta College)")
set(EXTENSION_DESCRIPTION "Enables real-time, multi-user collaboration for segmentation editing in 3D Slicer, featuring Google Docs-style synchronization and RBAC")
set(EXTENSION_DEPENDS "NA")
set(EXTENSION_ICONURL "/SlicerConnect.png")
set(EXTENSION_LICENSE_FILE "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(EXTENSION_SCREENSHOT_URLS "/Screenshots/Main.png")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(SlicerConnectLogin)
add_subdirectory(SlicerConnect)
add_subdirectory(SlicerConnectEditor)

## NEXT_MODULE
#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
