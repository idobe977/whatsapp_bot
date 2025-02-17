import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Box,
  Typography,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction
} from '@mui/material';
import { Add, Delete } from '@mui/icons-material';
import { Question } from '../types';

interface FlowEditorProps {
  open: boolean;
  onClose: () => void;
  question: Question;
  availableQuestions: Question[];
  onSave: (flow: Question['flow']) => void;
}

export const FlowEditor: React.FC<FlowEditorProps> = ({
  open,
  onClose,
  question,
  availableQuestions,
  onSave
}) => {
  const [flow, setFlow] = React.useState<Question['flow']>(question.flow || {});
  const [newCondition, setNewCondition] = React.useState({
    answer: '',
    goto: '',
    say: ''
  });

  const handleAddCondition = () => {
    if (newCondition.answer && (newCondition.goto || newCondition.say)) {
      const currentFlow = flow || {};
      if (!currentFlow.if) {
        // This is the first condition, set it as the 'if'
        setFlow({
          if: {
            answer: newCondition.answer,
            then: {
              goto: newCondition.goto || undefined,
              say: newCondition.say || undefined
            }
          }
        });
      } else {
        // Add to else_if array
        setFlow(prev => {
          const currentFlow = prev || {};
          return {
            ...currentFlow,
            else_if: [
              ...(currentFlow.else_if || []),
              {
                answer: newCondition.answer,
                then: {
                  goto: newCondition.goto || undefined,
                  say: newCondition.say || undefined
                }
              }
            ]
          };
        });
      }

      // Reset form
      setNewCondition({
        answer: '',
        goto: '',
        say: ''
      });
    }
  };

  const handleRemoveCondition = (index: number) => {
    if (index === -1) {
      // Remove the 'if' condition
      const currentFlow = { ...flow };
      const { else_if, ...rest } = currentFlow;
      if (else_if && else_if.length > 0) {
        // Move first else_if to if
        setFlow({
          if: else_if[0],
          else_if: else_if.slice(1)
        });
      } else {
        setFlow({});
      }
    } else {
      // Remove from else_if array
      setFlow(prev => {
        const currentFlow = prev || {};
        return {
          ...currentFlow,
          else_if: currentFlow.else_if?.filter((_, i) => i !== index)
        };
      });
    }
  };

  const handleSave = () => {
    onSave(flow);
    onClose();
  };

  const renderCondition = (condition: { answer: string; then: { goto?: string; say?: string } }, index: number) => {
    const targetQuestion = availableQuestions.find(q => q.id === condition.then.goto);
    
    return (
      <ListItem key={index}>
        <ListItemText
          primary={
            <Box>
              <Typography variant="subtitle2" component="span">
                אם התשובה היא: 
              </Typography>
              <Typography
                variant="body1"
                component="span"
                sx={{ mx: 1, fontWeight: 'bold' }}
              >
                {condition.answer}
              </Typography>
            </Box>
          }
          secondary={
            <Box sx={{ mt: 1 }}>
              {condition.then.say && (
                <Typography variant="body2" color="text.secondary">
                  אמור: {condition.then.say}
                </Typography>
              )}
              {condition.then.goto && (
                <Typography variant="body2" color="text.secondary">
                  עבור ל: {targetQuestion?.text || 'שאלה לא קיימת'}
                </Typography>
              )}
            </Box>
          }
        />
        <ListItemSecondaryAction>
          <IconButton
            edge="end"
            onClick={() => handleRemoveCondition(index)}
          >
            <Delete />
          </IconButton>
        </ListItemSecondaryAction>
      </ListItem>
    );
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>עריכת זרימת שאלות</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>
            תנאים קיימים
          </Typography>
          <List>
            {flow?.if && renderCondition(flow.if, -1)}
            {flow?.else_if?.map((condition, index) => renderCondition(condition, index))}
          </List>
        </Box>

        <Box sx={{ mt: 3 }}>
          <Typography variant="subtitle1" gutterBottom>
            הוסף תנאי חדש
          </Typography>
          <TextField
            fullWidth
            label="תנאי (תשובה)"
            value={newCondition.answer}
            onChange={(e) => setNewCondition(prev => ({ ...prev, answer: e.target.value }))}
            margin="normal"
          />
          <TextField
            fullWidth
            label="הודעה (אופציונלי)"
            value={newCondition.say}
            onChange={(e) => setNewCondition(prev => ({ ...prev, say: e.target.value }))}
            margin="normal"
          />
          <FormControl fullWidth margin="normal">
            <InputLabel>עבור לשאלה (אופציונלי)</InputLabel>
            <Select
              value={newCondition.goto}
              onChange={(e) => setNewCondition(prev => ({ ...prev, goto: e.target.value }))}
              label="עבור לשאלה (אופציונלי)"
            >
              <MenuItem value="">
                <em>ללא</em>
              </MenuItem>
              {availableQuestions
                .filter(q => q.id !== question.id)
                .map(q => (
                  <MenuItem key={q.id} value={q.id}>
                    {q.text}
                  </MenuItem>
                ))}
            </Select>
          </FormControl>
          <Button
            variant="contained"
            onClick={handleAddCondition}
            disabled={!newCondition.answer || (!newCondition.goto && !newCondition.say)}
            sx={{ mt: 2 }}
          >
            הוסף תנאי
          </Button>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>ביטול</Button>
        <Button onClick={handleSave} variant="contained">
          שמור
        </Button>
      </DialogActions>
    </Dialog>
  );
}; 