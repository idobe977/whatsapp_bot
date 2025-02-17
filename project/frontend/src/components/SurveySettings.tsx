import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Tabs,
  Tab,
  Typography,
  Switch,
  FormControlLabel,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  FormControl,
  InputLabel,
  Select,
  MenuItem
} from '@mui/material';
import { Add, Close, Delete } from '@mui/icons-material';
import { Survey } from '../types';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`settings-tabpanel-${index}`}
      aria-labelledby={`settings-tab-${index}`}
      {...other}
    >
      {value === index && (
        <Box sx={{ p: 3 }}>
          {children}
        </Box>
      )}
    </div>
  );
}

interface SurveySettingsProps {
  open: boolean;
  onClose: () => void;
  survey: Survey;
  onSave: (survey: Survey) => void;
}

interface FieldMapping {
  questionId: string;
  airtableField: string;
}

export const SurveySettings: React.FC<SurveySettingsProps> = ({
  open,
  onClose,
  survey,
  onSave
}) => {
  const [currentTab, setCurrentTab] = React.useState(0);
  const [localSurvey, setLocalSurvey] = React.useState<Survey>(survey);
  const [newTriggerPhrase, setNewTriggerPhrase] = React.useState('');
  const [fieldMappings, setFieldMappings] = React.useState<FieldMapping[]>(survey.airtable.fieldMappings || []);
  const [newMapping, setNewMapping] = React.useState({ questionId: '', airtableField: '' });

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  const handleSave = () => {
    onSave({
      ...localSurvey,
      airtable: {
        ...localSurvey.airtable,
        fieldMappings
      }
    });
    onClose();
  };

  const handleAddTriggerPhrase = () => {
    if (newTriggerPhrase.trim()) {
      setLocalSurvey(prev => ({
        ...prev,
        trigger_phrases: [...prev.trigger_phrases, newTriggerPhrase.trim()]
      }));
      setNewTriggerPhrase('');
    }
  };

  const handleRemoveTriggerPhrase = (phrase: string) => {
    setLocalSurvey(prev => ({
      ...prev,
      trigger_phrases: prev.trigger_phrases.filter(p => p !== phrase)
    }));
  };

  const handleAddMapping = () => {
    if (newMapping.questionId && newMapping.airtableField) {
      setFieldMappings([...fieldMappings, newMapping]);
      setNewMapping({ questionId: '', airtableField: '' });
    }
  };

  const handleRemoveMapping = (index: number) => {
    setFieldMappings(fieldMappings.filter((_, i) => i !== index));
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>הגדרות שאלון</DialogTitle>
      <DialogContent>
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tabs value={currentTab} onChange={handleTabChange}>
            <Tab label="כללי" />
            <Tab label="Airtable" />
            <Tab label="יומן" />
            <Tab label="AI" />
            <Tab label="הודעות" />
          </Tabs>
        </Box>

        <TabPanel value={currentTab} index={0}>
          <TextField
            fullWidth
            label="שם השאלון"
            value={localSurvey.name}
            onChange={(e) => setLocalSurvey(prev => ({ ...prev, name: e.target.value }))}
            margin="normal"
          />
          
          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle1" gutterBottom>
              ביטויי הפעלה
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              <TextField
                value={newTriggerPhrase}
                onChange={(e) => setNewTriggerPhrase(e.target.value)}
                placeholder="הוסף ביטוי הפעלה חדש"
                size="small"
              />
              <Button
                variant="contained"
                onClick={handleAddTriggerPhrase}
                startIcon={<Add />}
              >
                הוסף
              </Button>
            </Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {localSurvey.trigger_phrases.map((phrase) => (
                <Chip
                  key={phrase}
                  label={phrase}
                  onDelete={() => handleRemoveTriggerPhrase(phrase)}
                />
              ))}
            </Box>
          </Box>
        </TabPanel>

        <TabPanel value={currentTab} index={1}>
          <TextField
            fullWidth
            label="Airtable Base ID"
            value={localSurvey.airtable.base_id}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              airtable: { ...prev.airtable, base_id: e.target.value }
            }))}
            margin="normal"
          />
          <TextField
            fullWidth
            label="Airtable Table ID"
            value={localSurvey.airtable.table_id}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              airtable: { ...prev.airtable, table_id: e.target.value }
            }))}
            margin="normal"
          />

          <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>
            מיפוי שדות Airtable
          </Typography>

          <Box sx={{ mb: 2 }}>
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              <FormControl sx={{ flex: 1 }}>
                <InputLabel>שאלה</InputLabel>
                <Select
                  value={newMapping.questionId}
                  onChange={(e) => setNewMapping(prev => ({ ...prev, questionId: e.target.value }))}
                  label="שאלה"
                  size="small"
                >
                  {localSurvey.questions.map((question) => (
                    <MenuItem key={question.id} value={question.id}>
                      {question.text}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="שדה ב-Airtable"
                value={newMapping.airtableField}
                onChange={(e) => setNewMapping(prev => ({ ...prev, airtableField: e.target.value }))}
                size="small"
                sx={{ flex: 1 }}
              />
              <Button
                variant="contained"
                onClick={handleAddMapping}
                disabled={!newMapping.questionId || !newMapping.airtableField}
              >
                הוסף מיפוי
              </Button>
            </Box>

            <List>
              {fieldMappings.map((mapping, index) => {
                const question = localSurvey.questions.find(q => q.id === mapping.questionId);
                return (
                  <ListItem key={index}>
                    <ListItemText
                      primary={`שאלה: ${question?.text || 'לא נמצא'}`}
                      secondary={`שדה: ${mapping.airtableField}`}
                    />
                    <ListItemSecondaryAction>
                      <IconButton edge="end" onClick={() => handleRemoveMapping(index)}>
                        <Delete />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </ListItem>
                );
              })}
            </List>
          </Box>
        </TabPanel>

        <TabPanel value={currentTab} index={2}>
          {localSurvey.calendar_settings && (
            <>
              <TextField
                fullWidth
                label="Calendar ID"
                value={localSurvey.calendar_settings.calendar_id}
                onChange={(e) => setLocalSurvey(prev => ({
                  ...prev,
                  calendar_settings: {
                    ...prev.calendar_settings!,
                    calendar_id: e.target.value
                  }
                }))}
                margin="normal"
              />
              <TextField
                fullWidth
                label="משך פגישה (דקות)"
                type="number"
                value={localSurvey.calendar_settings.meeting_duration}
                onChange={(e) => setLocalSurvey(prev => ({
                  ...prev,
                  calendar_settings: {
                    ...prev.calendar_settings!,
                    meeting_duration: parseInt(e.target.value)
                  }
                }))}
                margin="normal"
              />
              <TextField
                fullWidth
                label="זמן חציצה בין פגישות (דקות)"
                type="number"
                value={localSurvey.calendar_settings.buffer_between_meetings}
                onChange={(e) => setLocalSurvey(prev => ({
                  ...prev,
                  calendar_settings: {
                    ...prev.calendar_settings!,
                    buffer_between_meetings: parseInt(e.target.value)
                  }
                }))}
                margin="normal"
              />
            </>
          )}
        </TabPanel>

        <TabPanel value={currentTab} index={3}>
          <Typography variant="subtitle1" gutterBottom>
            הגדרות רפלקציה
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={4}
            label="תבנית רפלקציה אמפתית"
            value={localSurvey.ai_prompts.reflections.empathetic.prompt}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              ai_prompts: {
                ...prev.ai_prompts,
                reflections: {
                  ...prev.ai_prompts.reflections,
                  empathetic: {
                    prompt: e.target.value
                  }
                }
              }
            }))}
            margin="normal"
          />
          <TextField
            fullWidth
            multiline
            rows={4}
            label="תבנית רפלקציה מקצועית"
            value={localSurvey.ai_prompts.reflections.professional.prompt}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              ai_prompts: {
                ...prev.ai_prompts,
                reflections: {
                  ...prev.ai_prompts.reflections,
                  professional: {
                    prompt: e.target.value
                  }
                }
              }
            }))}
            margin="normal"
          />
        </TabPanel>

        <TabPanel value={currentTab} index={4}>
          <TextField
            fullWidth
            multiline
            rows={2}
            label="הודעת פתיחה"
            value={localSurvey.messages.welcome}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              messages: {
                ...prev.messages,
                welcome: e.target.value
              }
            }))}
            margin="normal"
          />
          <TextField
            fullWidth
            multiline
            rows={2}
            label="הודעת סיום"
            value={localSurvey.messages.completion.text}
            onChange={(e) => setLocalSurvey(prev => ({
              ...prev,
              messages: {
                ...prev.messages,
                completion: {
                  ...prev.messages.completion,
                  text: e.target.value
                }
              }
            }))}
            margin="normal"
          />
          <FormControlLabel
            control={
              <Switch
                checked={localSurvey.messages.completion.should_generate_summary}
                onChange={(e) => setLocalSurvey(prev => ({
                  ...prev,
                  messages: {
                    ...prev.messages,
                    completion: {
                      ...prev.messages.completion,
                      should_generate_summary: e.target.checked
                    }
                  }
                }))}
              />
            }
            label="צור סיכום אוטומטי"
          />
        </TabPanel>
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