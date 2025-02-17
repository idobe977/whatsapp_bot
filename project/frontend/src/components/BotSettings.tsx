import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Typography,
  Switch,
  FormControlLabel,
  Divider,
  Alert,
  IconButton,
  Tooltip
} from '@mui/material';
import { Info } from '@mui/icons-material';

interface BotSettings {
  greenApi: {
    instance_id: string;
    api_token: string;
  };
  airtable: {
    api_key: string;
  };
  google: {
    credentials_file: string;
  };
  gemini: {
    api_key: string;
  };
  general: {
    log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    auto_retry_failed: boolean;
    max_retries: number;
    retry_delay: number;
  };
}

interface BotSettingsProps {
  open: boolean;
  onClose: () => void;
  settings: BotSettings;
  onSave: (settings: BotSettings) => void;
}

export const BotSettings: React.FC<BotSettingsProps> = ({
  open,
  onClose,
  settings,
  onSave
}) => {
  const [localSettings, setLocalSettings] = React.useState<BotSettings>(settings);
  const [testStatus, setTestStatus] = React.useState<{
    greenApi?: 'success' | 'error';
    airtable?: 'success' | 'error';
    google?: 'success' | 'error';
    gemini?: 'success' | 'error';
  }>({});

  const handleSave = () => {
    onSave(localSettings);
    onClose();
  };

  const handleTest = async (service: 'greenApi' | 'airtable' | 'google' | 'gemini') => {
    setTestStatus(prev => ({ ...prev, [service]: 'success' }));
    // TODO: Implement actual API testing
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>הגדרות בוט</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 4 }}>
          <Typography variant="h6" gutterBottom>
            Green API
            <Tooltip title="הגדרות התחברות ל-WhatsApp">
              <IconButton size="small" sx={{ ml: 1 }}>
                <Info fontSize="small" />
              </IconButton>
            </Tooltip>
          </Typography>
          <TextField
            fullWidth
            label="Instance ID"
            value={localSettings.greenApi.instance_id}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              greenApi: { ...prev.greenApi, instance_id: e.target.value }
            }))}
            margin="normal"
          />
          <TextField
            fullWidth
            label="API Token"
            type="password"
            value={localSettings.greenApi.api_token}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              greenApi: { ...prev.greenApi, api_token: e.target.value }
            }))}
            margin="normal"
          />
          <Button
            variant="outlined"
            onClick={() => handleTest('greenApi')}
            sx={{ mt: 1 }}
          >
            בדוק חיבור
          </Button>
          {testStatus.greenApi && (
            <Alert severity={testStatus.greenApi} sx={{ mt: 1 }}>
              {testStatus.greenApi === 'success' ? 'החיבור תקין' : 'החיבור נכשל'}
            </Alert>
          )}
        </Box>

        <Divider sx={{ my: 3 }} />

        <Box sx={{ mb: 4 }}>
          <Typography variant="h6" gutterBottom>
            Airtable
            <Tooltip title="הגדרות התחברות ל-Airtable">
              <IconButton size="small" sx={{ ml: 1 }}>
                <Info fontSize="small" />
              </IconButton>
            </Tooltip>
          </Typography>
          <TextField
            fullWidth
            label="API Key"
            type="password"
            value={localSettings.airtable.api_key}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              airtable: { ...prev.airtable, api_key: e.target.value }
            }))}
            margin="normal"
          />
          <Button
            variant="outlined"
            onClick={() => handleTest('airtable')}
            sx={{ mt: 1 }}
          >
            בדוק חיבור
          </Button>
          {testStatus.airtable && (
            <Alert severity={testStatus.airtable} sx={{ mt: 1 }}>
              {testStatus.airtable === 'success' ? 'החיבור תקין' : 'החיבור נכשל'}
            </Alert>
          )}
        </Box>

        <Divider sx={{ my: 3 }} />

        <Box sx={{ mb: 4 }}>
          <Typography variant="h6" gutterBottom>
            Google Calendar
            <Tooltip title="הגדרות התחברות ליומן גוגל">
              <IconButton size="small" sx={{ ml: 1 }}>
                <Info fontSize="small" />
              </IconButton>
            </Tooltip>
          </Typography>
          <TextField
            fullWidth
            label="קובץ הרשאות"
            value={localSettings.google.credentials_file}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              google: { ...prev.google, credentials_file: e.target.value }
            }))}
            margin="normal"
          />
          <Button
            variant="outlined"
            onClick={() => handleTest('google')}
            sx={{ mt: 1 }}
          >
            בדוק חיבור
          </Button>
          {testStatus.google && (
            <Alert severity={testStatus.google} sx={{ mt: 1 }}>
              {testStatus.google === 'success' ? 'החיבור תקין' : 'החיבור נכשל'}
            </Alert>
          )}
        </Box>

        <Divider sx={{ my: 3 }} />

        <Box sx={{ mb: 4 }}>
          <Typography variant="h6" gutterBottom>
            Gemini AI
            <Tooltip title="הגדרות התחברות ל-Gemini AI">
              <IconButton size="small" sx={{ ml: 1 }}>
                <Info fontSize="small" />
              </IconButton>
            </Tooltip>
          </Typography>
          <TextField
            fullWidth
            label="API Key"
            type="password"
            value={localSettings.gemini.api_key}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              gemini: { ...prev.gemini, api_key: e.target.value }
            }))}
            margin="normal"
          />
          <Button
            variant="outlined"
            onClick={() => handleTest('gemini')}
            sx={{ mt: 1 }}
          >
            בדוק חיבור
          </Button>
          {testStatus.gemini && (
            <Alert severity={testStatus.gemini} sx={{ mt: 1 }}>
              {testStatus.gemini === 'success' ? 'החיבור תקין' : 'החיבור נכשל'}
            </Alert>
          )}
        </Box>

        <Divider sx={{ my: 3 }} />

        <Box>
          <Typography variant="h6" gutterBottom>
            הגדרות כלליות
          </Typography>
          <FormControlLabel
            control={
              <Switch
                checked={localSettings.general.auto_retry_failed}
                onChange={(e) => setLocalSettings(prev => ({
                  ...prev,
                  general: {
                    ...prev.general,
                    auto_retry_failed: e.target.checked
                  }
                }))}
              />
            }
            label="נסה שוב אוטומטית במקרה של כשל"
          />
          <TextField
            fullWidth
            label="מספר נסיונות מקסימלי"
            type="number"
            value={localSettings.general.max_retries}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              general: {
                ...prev.general,
                max_retries: parseInt(e.target.value)
              }
            }))}
            margin="normal"
            disabled={!localSettings.general.auto_retry_failed}
          />
          <TextField
            fullWidth
            label="זמן המתנה בין נסיונות (שניות)"
            type="number"
            value={localSettings.general.retry_delay}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              general: {
                ...prev.general,
                retry_delay: parseInt(e.target.value)
              }
            }))}
            margin="normal"
            disabled={!localSettings.general.auto_retry_failed}
          />
          <TextField
            fullWidth
            select
            label="רמת יומן"
            value={localSettings.general.log_level}
            onChange={(e) => setLocalSettings(prev => ({
              ...prev,
              general: {
                ...prev.general,
                log_level: e.target.value as BotSettings['general']['log_level']
              }
            }))}
            margin="normal"
            SelectProps={{
              native: true
            }}
          >
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </TextField>
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