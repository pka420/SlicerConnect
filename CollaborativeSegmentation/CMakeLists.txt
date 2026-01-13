find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

set(module_name CollaborativeSegmentation) 

slicerMacroBuildScriptedModule(
  NAME ${module_name}
  SCRIPTS ${module_name}.py
  RESOURCES "Resources/Icons/${module_name}.png;Resources/UI/${module_name}.ui"
)


