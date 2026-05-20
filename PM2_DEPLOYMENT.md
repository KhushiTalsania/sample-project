# PM2 Deployment Configuration

This directory contains PM2 configuration files for different environments.

## Configuration Files

### Development
- **File**: `pm2.development.json`
- **Port**: 8000
- **Features**: Auto-reload, file watching, single instance
- **Usage**: `pm2 start pm2.development.json`

### Staging
- **File**: `pm2.staging.json`
- **Port**: 8300
- **Features**: Single instance, memory monitoring, staging environment
- **Usage**: `pm2 start pm2.staging.json`

### Production
- **File**: `pm2.production.json`
- **Port**: 8300
- **Features**: Cluster mode, 4 workers, memory monitoring, production environment
- **Usage**: `pm2 start pm2.production.json`

## Quick Commands

### Start Services
```bash
# Development
pm2 start pm2.development.json

# Staging
pm2 start pm2.staging.json

# Production
pm2 start pm2.production.json
```

### Stop Services
```bash
# Stop all
pm2 stop all

# Stop specific
pm2 stop simulated-betting-backend-staging:8300
```

### Restart Services
```bash
# Restart all
pm2 restart all

# Restart specific
pm2 restart simulated-betting-backend-staging:8300
```

### Monitor Services
```bash
# View status
pm2 status

# View all logs
pm2 logs

# View specific app logs
pm2 logs simulated-betting-backend-staging:8300

# View last 100 lines
pm2 logs --lines 100

# Monitor in real-time
pm2 monit
```

### Delete Services
```bash
# Delete all
pm2 delete all

# Delete specific
pm2 delete simulated-betting-backend-staging:8300
```

## Environment Variables

All configurations include:
- `PYTHONPATH`: Project root path
- `ENV`: Environment (development/staging/production)
- `PORT`: Server port
- `HOST`: Server host (0.0.0.0)

## Log Files

PM2 uses default logging behavior (no custom log files configured):
- Logs are managed by PM2's default system
- Use `pm2 logs` to view real-time logs
- Use `pm2 logs --lines 100` to view last 100 lines

## Socket.IO Integration

All configurations use `main:socket_app` to ensure Socket.IO is properly loaded:
- WebSocket endpoint: `ws://your-server:port/socket.io/`
- Health check: `http://your-server:port/socketio/health`
- Stats: `http://your-server:port/socketio/stats`

## Memory Management

- **Development**: 500MB restart threshold
- **Staging**: 1GB restart threshold
- **Production**: 1GB restart threshold with cluster mode

## File Watching (Development Only)

Development configuration watches for file changes and auto-restarts:
- Watches: Python files, configuration files
- Ignores: node_modules, logs, uploads, .git

## Important Notes

1. **Socket.IO**: All configs use `main:socket_app` (not `main:app`)
2. **Ports**: Development uses 8000, Staging/Production use 8300
3. **Workers**: Production uses 4 cluster workers for better performance
4. **Logs**: Uses PM2 default logging (no custom log files)
5. **Environment**: Set via `ENV` variable in each config

## Troubleshooting

### Socket.IO Not Working
- Ensure using `main:socket_app` in PM2 config
- Check logs: `pm2 logs simulated-betting-backend-staging:8300`
- Test endpoint: `curl http://localhost:8300/socketio/health`

### Port Issues
- Check if port is already in use: `netstat -tulpn | grep :8300`
- Verify PM2 config has correct port
- Check firewall settings

### Memory Issues
- Monitor memory usage: `pm2 monit`
- Adjust `max_memory_restart` in config
- Consider increasing server resources
