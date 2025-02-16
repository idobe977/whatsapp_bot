import React from 'react';
import ReactFlow, { 
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Node,
  Edge,
  NodeTypes,
  NodeProps,
  ConnectionMode
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Box, AppBar, Toolbar, Typography, IconButton, SpeedDial, SpeedDialAction } from '@mui/material';
import { Save, Undo, Redo, Preview, Settings, Add, TextFields, Poll, Mic, Schedule } from '@mui/icons-material';
import { NodeData, Survey, Question } from '../types';
import { QuestionNode } from './QuestionNode';
import { AddQuestionDialog } from './AddQuestionDialog';

interface SurveyBuilderProps {
  survey: Survey;
  onBack: () => void;
  onSettingsClick: () => void;
}

const nodeTypes: NodeTypes = {
  questionNode: QuestionNode as React.ComponentType<NodeProps>
};

export const SurveyBuilder: React.FC<SurveyBuilderProps> = ({ survey, onBack, onSettingsClick }) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [addQuestionOpen, setAddQuestionOpen] = React.useState(false);
  const [speedDialOpen, setSpeedDialOpen] = React.useState(false);
  const [history, setHistory] = React.useState<Array<{ nodes: any[]; edges: any[] }>>([]);
  const [historyIndex, setHistoryIndex] = React.useState(-1);

  // Load initial nodes from survey
  React.useEffect(() => {
    const initialNodes = survey.questions.map((question, index) => ({
      id: question.id,
      type: 'questionNode',
      position: { x: 250, y: index * 150 },
      data: question
    }));
    setNodes(initialNodes);
  }, [survey, setNodes]);

  const onConnect = React.useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge(connection, eds));
      saveToHistory();
    },
    [setEdges]
  );

  const handleAddQuestion = (question: Question) => {
    const newNode = {
      id: question.id,
      type: 'questionNode',
      position: { x: 250, y: nodes.length * 150 },
      data: question
    };
    setNodes((nds) => [...nds, newNode]);
    saveToHistory();
  };

  const saveToHistory = () => {
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push({ nodes: nodes, edges: edges });
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
  };

  const handleUndo = () => {
    if (historyIndex > 0) {
      const prevState = history[historyIndex - 1];
      setNodes(prevState.nodes);
      setEdges(prevState.edges);
      setHistoryIndex(historyIndex - 1);
    }
  };

  const handleRedo = () => {
    if (historyIndex < history.length - 1) {
      const nextState = history[historyIndex + 1];
      setNodes(nextState.nodes);
      setEdges(nextState.edges);
      setHistoryIndex(historyIndex + 1);
    }
  };

  const handleSave = () => {
    // TODO: Implement save functionality
    console.log('Saving survey:', { nodes, edges });
  };

  const handlePreview = () => {
    // TODO: Implement preview functionality
    console.log('Preview survey:', { nodes, edges });
  };

  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            בונה השאלונים החכם
          </Typography>
          <IconButton color="inherit" title="שמור" onClick={handleSave}>
            <Save />
          </IconButton>
          <IconButton color="inherit" title="בטל" onClick={handleUndo} disabled={historyIndex <= 0}>
            <Undo />
          </IconButton>
          <IconButton color="inherit" title="בצע שוב" onClick={handleRedo} disabled={historyIndex >= history.length - 1}>
            <Redo />
          </IconButton>
          <IconButton color="inherit" title="תצוגה מקדימה" onClick={handlePreview}>
            <Preview />
          </IconButton>
          <IconButton color="inherit" title="הגדרות" onClick={onSettingsClick}>
            <Settings />
          </IconButton>
        </Toolbar>
      </AppBar>

      <Box sx={{ flexGrow: 1, position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          defaultEdgeOptions={{
            type: 'smoothstep',
            animated: true,
            style: { stroke: '#1976d2', strokeWidth: 2 }
          }}
          snapToGrid={true}
          snapGrid={[15, 15]}
          deleteKeyCode="Delete"
          selectionKeyCode="Shift"
          multiSelectionKeyCode="Control"
          zoomOnScroll={true}
          zoomOnPinch={true}
          panOnScroll={true}
          panOnDrag={true}
          connectOnClick={false}
          connectionMode={ConnectionMode.Loose}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>

        <SpeedDial
          ariaLabel="הוסף שאלה"
          sx={{ 
            position: 'absolute', 
            bottom: 32, 
            left: 32
          }}
          icon={<Add />}
          open={speedDialOpen}
          onClose={() => setSpeedDialOpen(false)}
          onClick={() => {
            setSpeedDialOpen(false);
            setAddQuestionOpen(true);
          }}
        />
      </Box>

      <AddQuestionDialog
        open={addQuestionOpen}
        onClose={() => setAddQuestionOpen(false)}
        onAdd={(question) => {
          handleAddQuestion(question);
          setAddQuestionOpen(false);
        }}
      />
    </Box>
  );
}; 