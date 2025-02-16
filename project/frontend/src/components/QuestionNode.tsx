import React from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';
import { 
  Card, 
  CardContent, 
  Typography, 
  IconButton, 
  Box,
  Menu,
  MenuItem,
  TextField,
  Select,
  FormControl,
  InputLabel
} from '@mui/material';
import { 
  MoreVert, 
  Delete, 
  ContentCopy,
  Psychology,
  Schedule,
  Poll,
  TextFields,
  Mic
} from '@mui/icons-material';
import { FlowEditor } from './FlowEditor';

interface QuestionNodeData {
  id: string;
  text: string;
  type: 'text' | 'poll' | 'voice' | 'meeting_scheduler';
  options?: string[];
  reflection?: {
    type: 'empathetic' | 'professional';
    enabled: boolean;
  };
  flow?: {
    if?: {
      answer: string;
      then: {
        say?: string;
        goto?: string;
      };
    };
    else_if?: Array<{
      answer: string;
      then: {
        say?: string;
        goto?: string;
      };
    }>;
  };
}

interface QuestionNodeProps {
  data: QuestionNodeData;
  isConnectable: boolean;
  selected?: boolean;
  id: string;
}

const questionTypeIcons = {
  text: <TextFields />,
  poll: <Poll />,
  voice: <Mic />,
  meeting_scheduler: <Schedule />
};

export const QuestionNode: React.FC<NodeProps<QuestionNodeData>> = ({ data, isConnectable, selected, id }) => {
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const [isEditing, setIsEditing] = React.useState(false);
  const [showFlowEditor, setShowFlowEditor] = React.useState(false);
  const { setNodes, getNode, getNodes } = useReactFlow();

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation();
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleDuplicate = () => {
    const node = getNode(id);
    if (node) {
      const newNode = {
        ...node,
        id: `${node.id}_copy_${Date.now()}`,
        position: {
          x: node.position.x + 50,
          y: node.position.y + 50
        },
        data: { ...node.data }
      };
      setNodes((nodes) => [...nodes, newNode]);
    }
    handleMenuClose();
  };

  const handleDelete = () => {
    setNodes((nodes) => nodes.filter((node) => node.id !== id));
    handleMenuClose();
  };

  const handleReflectionSettings = () => {
    setShowFlowEditor(true);
    handleMenuClose();
  };

  const handleTextChange = (newText: string) => {
    setNodes((nodes) =>
      nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, text: newText } } : node
      )
    );
  };

  return (
    <Card 
      sx={{ 
        minWidth: 250,
        maxWidth: 350,
        border: selected ? '2px solid #1976d2' : '1px solid #ccc'
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={isConnectable}
      />
      
      <Box sx={{ display: 'flex', alignItems: 'center', p: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {questionTypeIcons[data.type]}
          {data.reflection?.enabled && <Psychology color="primary" />}
        </Box>
        
        <IconButton 
          size="small" 
          sx={{ marginLeft: 'auto' }}
          onClick={handleMenuOpen}
        >
          <MoreVert />
        </IconButton>
      </Box>

      <CardContent>
        {isEditing ? (
          <TextField
            fullWidth
            multiline
            value={data.text}
            onChange={(e) => handleTextChange(e.target.value)}
            onBlur={() => setIsEditing(false)}
            autoFocus
          />
        ) : (
          <Typography 
            variant="body1" 
            onClick={() => setIsEditing(true)}
            sx={{ cursor: 'pointer' }}
          >
            {data.text}
          </Typography>
        )}

        {data.type === 'poll' && data.options && (
          <Box sx={{ mt: 2 }}>
            {data.options.map((option, index) => (
              <Typography key={index} variant="body2" color="text.secondary">
                • {option}
              </Typography>
            ))}
          </Box>
        )}
      </CardContent>

      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={isConnectable}
      />

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={handleDuplicate}>
          <ContentCopy sx={{ mr: 1 }} /> שכפל
        </MenuItem>
        <MenuItem onClick={handleReflectionSettings}>
          <Psychology sx={{ mr: 1 }} /> הגדר התניות
        </MenuItem>
        <MenuItem onClick={handleDelete}>
          <Delete sx={{ mr: 1 }} color="error" /> מחק
        </MenuItem>
      </Menu>

      {showFlowEditor && (
        <FlowEditor
          open={showFlowEditor}
          onClose={() => setShowFlowEditor(false)}
          question={data}
          availableQuestions={getNodes().map(n => n.data)}
          onSave={(flow: QuestionNodeData['flow']) => {
            setNodes((nodes) =>
              nodes.map((node) =>
                node.id === id ? { ...node, data: { ...node.data, flow } } : node
              )
            );
            setShowFlowEditor(false);
          }}
        />
      )}
    </Card>
  );
}; 