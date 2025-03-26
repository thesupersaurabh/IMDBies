<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" 
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns="http://www.w3.org/1999/xhtml">

    <xsl:output method="html" indent="yes" encoding="UTF-8" doctype-public="-//W3C//DTD XHTML 1.0 Transitional//EN" doctype-system="http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"/>

    <xsl:template match="/">
        <html xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <title>XML Sitemap - IMDBie</title>
                <meta charset="UTF-8"/>
                <meta name="viewport" content="width=device-width, initial-scale=1"/>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                        font-size: 14px;
                        color: #333;
                        max-width: 75%;
                        margin: 0 auto;
                        padding: 20px;
                        background: #f8f9fa;
                    }
                    h1 {
                        color: #2c3e50;
                        font-size: 24px;
                        font-weight: bold;
                        margin-bottom: 20px;
                    }
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        background: white;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                        border-radius: 8px;
                        margin-bottom: 20px;
                    }
                    th {
                        background: #3498db;
                        color: white;
                        text-align: left;
                        padding: 12px;
                        font-weight: 500;
                    }
                    td {
                        padding: 12px;
                        border-top: 1px solid #eee;
                        vertical-align: top;
                    }
                    tr:hover {
                        background: #f5f6fa;
                    }
                    .url {
                        color: #2980b9;
                        text-decoration: none;
                        word-break: break-all;
                    }
                    .url:hover {
                        text-decoration: underline;
                    }
                    .priority-high {
                        color: #27ae60;
                        font-weight: bold;
                    }
                    .priority-medium {
                        color: #f39c12;
                    }
                    .priority-low {
                        color: #95a5a6;
                    }
                    .summary {
                        background: white;
                        padding: 15px;
                        margin-bottom: 20px;
                        border-radius: 8px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }
                </style>
            </head>
            <body>
                <h1>IMDBie Sitemap</h1>
                <div class="summary">
                    <p>Total URLs: <xsl:value-of select="count(//url)"/></p>
                    <p>Last Updated: <xsl:value-of select="substring(//url[1]/lastmod, 1, 10)"/></p>
                </div>
                <table>
                    <tr>
                        <th>URL</th>
                        <th>Last Modified</th>
                        <th>Change Freq</th>
                        <th>Priority</th>
                    </tr>
                    <xsl:for-each select="urlset/url">
                        <tr>
                            <td>
                                <a href="{loc}" class="url"><xsl:value-of select="loc"/></a>
                            </td>
                            <td><xsl:value-of select="lastmod"/></td>
                            <td><xsl:value-of select="changefreq"/></td>
                            <td>
                                <xsl:choose>
                                    <xsl:when test="number(priority) >= 0.8">
                                        <span class="priority-high"><xsl:value-of select="priority"/></span>
                                    </xsl:when>
                                    <xsl:when test="number(priority) >= 0.5">
                                        <span class="priority-medium"><xsl:value-of select="priority"/></span>
                                    </xsl:when>
                                    <xsl:otherwise>
                                        <span class="priority-low"><xsl:value-of select="priority"/></span>
                                    </xsl:otherwise>
                                </xsl:choose>
                            </td>
                        </tr>
                    </xsl:for-each>
                </table>
            </body>
        </html>
    </xsl:template>
</xsl:stylesheet> 