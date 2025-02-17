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
  Chip
} from '@mui/material';
import { Add, Delete } from '@mui/icons-material';
import { Question } from '../types';

interface AddQuestionDialogProps {
  open: boolean;
  onClose: () => void;
  onAdd: (question: Question) => void;
}

export const AddQuestionDialog: React.FC<AddQuestionDialogProps> = ({
  open,
  onClose,
  onAdd
}) => {
  const [questionType, setQuestionType] = React.useState<Question['type']>('text');
  const [questionText, setQuestionText] = React.useState('');
  const [options, setOptions] = React.useState<string[]>([]);
  const [newOption, setNewOption] = React.useState('');
  const [reflection, setReflection] = React.useState({
    enabled: false,
    type: 'empathetic'
  });

  const handleAddOption = () => {
    if (newOption.trim()) {
      setOptions([...options, newOption.trim()]);
      setNewOption('');
    }
  };

  const handleRemoveOption = (optionToRemove: string) => {
    setOptions(options.filter(option => option !== optionToRemove));
  };

  const handleAdd = () => {
    const newQuestion: Question = {
      id: `q_${Date.now()}`,
      type: questionType,
      text: questionText,
      ...(questionType === 'poll' && { options }),
      ...(reflection.enabled && {
        reflection: {
          type: reflection.type as 'empathetic' | 'professional',
          enabled: true
        }
      })
    };

    onAdd(newQuestion);
    onClose();
    
    // Reset form
    setQuestionType('text');
    setQuestionText('');
    setOptions([]);
    setNewOption('');
    setReflection({ enabled: false, type: 'empathetic' });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>הוספת שאלה חדשה</DialogTitle>
      <DialogContent>
        <FormControl fullWidth margin="normal">
          <InputLabel>סוג שאלה</InputLabel>
          <Select
            value={questionType}
            onChange={(e) => setQuestionType(e.target.value as Question['type'])}
            label="סוג שאלה"
          >
            <MenuItem value="text">טקסט</MenuItem>
            <MenuItem value="poll">סקר</MenuItem>
            <MenuItem value="voice">הקלטה קולית</MenuItem>
            <MenuItem value="meeting_scheduler">תזמון פגישה</MenuItem>
          </Select>
        </FormControl>

        <TextField
          fullWidth
          multiline
          rows={3}
          label="טקסט השאלה"
          value={questionText}
          onChange={(e) => setQuestionText(e.target.value)}
          margin="normal"
        />

        {questionType === 'poll' && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              אפשרויות
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              <TextField
                value={newOption}
                onChange={(e) => setNewOption(e.target.value)}
                placeholder="הוסף אפשרות חדשה"
                size="small"
              />
              <Button
                variant="contained"
                onClick={handleAddOption}
                startIcon={<Add />}
              >
                הוסף
              </Button>
            </Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {options.map((option) => (
                <Chip
                  key={option}
                  label={option}
                  onDelete={() => handleRemoveOption(option)}
                />
              ))}
            </Box>
          </Box>
        )}

        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            הגדרות רפלקציה
          </Typography>
          <FormControl fullWidth margin="normal">
            <InputLabel>סוג רפלקציה</InputLabel>
            <Select
              value={reflection.type}
              onChange={(e) => setReflection(prev => ({ ...prev, type: e.target.value }))}
              label="סוג רפלקציה"
              disabled={!reflection.enabled}
            >
              <MenuItem value="empathetic">אמפתית</MenuItem>
              <MenuItem value="professional">מקצועית</MenuItem>
            </Select>
          </FormControl>
          <Button
            variant={reflection.enabled ? "contained" : "outlined"}
            onClick={() => setReflection(prev => ({ ...prev, enabled: !prev.enabled }))}
            sx={{ mt: 1 }}
          >
            {reflection.enabled ? 'רפלקציה מופעלת' : 'הפעל רפלקציה'}
          </Button>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>ביטול</Button>
        <Button 
          onClick={handleAdd} 
          variant="contained"
          disabled={!questionText.trim() || (questionType === 'poll' && options.length < 2)}
        >
          הוסף
        </Button>
      </DialogActions>
    </Dialog>
  );
}; 