import { Still, Folder } from "remotion";
import { CLIOutput } from "./components/CLIOutput";
import { ArchitectureDiagram } from "./components/ArchitectureDiagram";
import { DetectionCategories } from "./components/DetectionCategories";

export const RemotionRoot: React.FC = () => {
  return (
    <Folder name="Screenshots">
      <Still
        id="CLIOutput"
        component={CLIOutput}
        width={1200}
        height={800}
      />
      <Still
        id="ArchitectureDiagram"
        component={ArchitectureDiagram}
        width={1200}
        height={700}
      />
      <Still
        id="DetectionCategories"
        component={DetectionCategories}
        width={1200}
        height={900}
      />
    </Folder>
  );
};
