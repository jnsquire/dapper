# Deployment Guide

This guide covers deploying the "Things the Humans Should Know" wiki to a VPS (Virtual Private Server).

## Prerequisites

- A VPS with SSH access (Ubuntu/Debian recommended)
- Domain name (optional, but recommended)
- Basic command line knowledge

## Quick Deployment Steps

### 1. Install Bun on Your VPS

```bash
# SSH into your VPS
ssh user@your-vps-ip

# Install Bun
curl -fsSL https://bun.sh/install | bash

# Add Bun to PATH (add to ~/.bashrc or ~/.bash_profile)
export PATH="$HOME/.bun/bin:$PATH"
source ~/.bashrc
```

### 2. Clone and Setup the Project

```bash
# Clone the repository
git clone https://github.com/yourusername/dapper.git
cd dapper/wiki

# Install dependencies
bun install

# Build the site
bun run build
```

### 3. Run the Server

#### Option A: Direct Bun Server (Simple)

```bash
# Run on port 80 (requires sudo or elevated privileges)
sudo PORT=80 bun run start

# Or run on a higher port without sudo
PORT=8080 bun run start
```

#### Option B: Using a Process Manager (Recommended)

Install PM2 (process manager):

```bash
# Install PM2 globally
npm install -g pm2

# Start the wiki with PM2
cd ~/dapper/wiki
PORT=3000 pm2 start "bun run start" --name wiki

# Make it start on system boot
pm2 startup
pm2 save
```

#### Option C: Systemd Service (Production)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/wiki.service
```

Add this content (adjust paths and user):

```ini
[Unit]
Description=Things Humans Should Know Wiki
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/dapper/wiki
Environment="PATH=/home/your-username/.bun/bin:/usr/bin:/bin"
Environment="PORT=3000"
ExecStart=/home/your-username/.bun/bin/bun run start
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wiki
sudo systemctl start wiki
sudo systemctl status wiki
```

### 4. Setup Nginx Reverse Proxy (Recommended)

Install Nginx:

```bash
sudo apt update
sudo apt install nginx
```

Create Nginx configuration:

```bash
sudo nano /etc/nginx/sites-available/wiki
```

Add this configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/wiki /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5. Setup SSL/HTTPS with Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Auto-renewal is set up automatically
```

## Static Deployment (Alternative)

If you prefer serving only static files without Bun:

### Build Static Files

```bash
cd ~/dapper/wiki
bun run build
```

### Serve with Nginx Only

Update Nginx configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    root /home/your-username/dapper/wiki/dist;
    index index.html;

    location / {
        try_files $uri $uri.html $uri/ =404;
    }
}
```

This approach is simpler but requires rebuilding and deploying for content changes.

## Updating Content

### Option 1: Direct Editing on VPS

```bash
# SSH into VPS
ssh user@your-vps-ip

# Edit content
cd ~/dapper/wiki/content/articles
nano new-article.md

# Rebuild
cd ~/dapper/wiki
bun run build

# Restart service (if using systemd)
sudo systemctl restart wiki
```

### Option 2: Git Workflow (Recommended)

```bash
# On your local machine, make changes and commit
cd wiki/content/articles
# ... edit files ...
git add .
git commit -m "Add new article"
git push

# On VPS, pull and rebuild
ssh user@your-vps-ip
cd ~/dapper/wiki
git pull
bun run build
sudo systemctl restart wiki  # if using systemd
```

### Option 3: Automated with Git Hooks

Setup a post-receive hook to auto-deploy on push:

```bash
# On VPS, setup bare repository
cd ~
git init --bare wiki-repo.git

# Create post-receive hook
nano wiki-repo.git/hooks/post-receive
```

Add this script:

```bash
#!/bin/bash
WORK_TREE=/home/your-username/dapper/wiki
GIT_DIR=/home/your-username/wiki-repo.git

git --work-tree=$WORK_TREE --git-dir=$GIT_DIR checkout -f
cd $WORK_TREE
bun run build
systemctl restart wiki
```

Make it executable:

```bash
chmod +x wiki-repo.git/hooks/post-receive
```

On your local machine:

```bash
git remote add production user@your-vps-ip:wiki-repo.git
git push production main
```

## Monitoring and Maintenance

### Check Server Status

```bash
# If using systemd
sudo systemctl status wiki

# If using PM2
pm2 status
pm2 logs wiki

# Check Nginx
sudo systemctl status nginx
sudo nginx -t
```

### View Logs

```bash
# Systemd logs
sudo journalctl -u wiki -f

# PM2 logs
pm2 logs wiki

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Backup

Regular backups of content:

```bash
# Backup content directory
tar -czf wiki-content-$(date +%Y%m%d).tar.gz ~/dapper/wiki/content

# Or use automated backup solution
```

## Security Best Practices

1. **Keep system updated**
   ```bash
   sudo apt update && sudo apt upgrade
   ```

2. **Setup firewall**
   ```bash
   sudo ufw allow 22    # SSH
   sudo ufw allow 80    # HTTP
   sudo ufw allow 443   # HTTPS
   sudo ufw enable
   ```

3. **Secure SSH**
   - Use key-based authentication
   - Disable password login
   - Change default port (optional)

4. **Regular updates**
   - Update Bun: `bun upgrade`
   - Update dependencies: `bun update`
   - Update system packages

5. **Monitor logs** for suspicious activity

## Performance Optimization

### Enable Gzip Compression in Nginx

Add to Nginx configuration:

```nginx
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss;
```

### Add Caching Headers

```nginx
location ~* \.(css|js|jpg|jpeg|png|gif|ico|svg)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

### CDN (Optional)

For global audiences, consider using a CDN like:
- Cloudflare (free tier available)
- AWS CloudFront
- DigitalOcean Spaces CDN

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
sudo lsof -i :3000
# Kill it
sudo kill -9 <PID>
```

### Permission Errors

```bash
# Fix ownership
sudo chown -R your-username:your-username ~/dapper

# Fix permissions
chmod -R 755 ~/dapper/wiki
```

### Service Won't Start

```bash
# Check logs
sudo journalctl -u wiki -n 50

# Verify Bun installation
which bun
bun --version
```

## Cost Estimates

Typical VPS options:

- **DigitalOcean**: $6/month (1GB RAM, 1 CPU)
- **Linode**: $5/month (1GB RAM, 1 CPU)
- **Vultr**: $6/month (1GB RAM, 1 CPU)
- **AWS Lightsail**: $5/month (512MB RAM, 1 CPU)

Plus optional:
- Domain name: ~$10-15/year
- SSL certificate: Free (Let's Encrypt)

## Support

For issues or questions:
- Check the main README.md
- Review Bun documentation: https://bun.sh/docs
- Check Nginx documentation for proxy setup

---

Happy deploying!
