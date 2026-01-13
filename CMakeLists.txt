cmake_minimum_required(VERSION 3.16.3)

project(SlicerConnect)
#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/SlicerConnect")
set(EXTENSION_CONTRIBUTORS "Piyush Khurana (Aryabhatta College)")
set(EXTENSION_DESCRIPTION "For 3d Slicer Collaboration	")
set(EXTENSION_ICONURL "https://www.example.com/Slicer/Extensions/SlicerConnect.png")
set(EXTENSION_SCREENSHOTURLS "https://www.example.com/Slicer/Extensions/SlicerConnect/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA")
set(EXTENSION_ICONURL "/SlicerConnect.png")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(Login)
add_subdirectory(SyncData)

## NEXT_MODULE
#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
