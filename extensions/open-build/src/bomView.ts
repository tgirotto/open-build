/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

interface BomRow {
	partNumber?: string;
	description?: string;
	quantity?: number;
	vendor?: string;
}

let panel: vscode.WebviewPanel | undefined;

export function registerBomView(context: vscode.ExtensionContext): vscode.Disposable {
	return vscode.commands.registerCommand('openBuild.showBom', () => openBom(context));
}

async function openBom(context: vscode.ExtensionContext): Promise<void> {
	const folder = vscode.workspace.workspaceFolders?.[0];
	if (!folder) {
		void vscode.window.showErrorMessage(vscode.l10n.t("Open a folder before showing the bill of materials."));
		return;
	}

	if (panel) {
		panel.reveal(vscode.ViewColumn.Beside);
		await postBom(folder);
		return;
	}

	const created = vscode.window.createWebviewPanel(
		'openBuild.bom',
		vscode.l10n.t("Bill of Materials"),
		vscode.ViewColumn.Beside,
		{
			enableScripts: true,
			localResourceRoots: [context.extensionUri],
		},
	);
	panel = created;
	const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, 'bom.json'));
	const refresh = () => { void postBom(folder); };
	watcher.onDidCreate(refresh);
	watcher.onDidChange(refresh);
	const messages = created.webview.onDidReceiveMessage(message => {
		if (message && message.type === 'ready') {
			void postBom(folder);
		}
	});
	created.onDidDispose(() => {
		messages.dispose();
		watcher.dispose();
		panel = undefined;
	});
	context.subscriptions.push(created);
	created.webview.html = html(created.webview, vscode.Uri.joinPath(context.extensionUri, 'media', 'bom.js'));
}

async function postBom(folder: vscode.WorkspaceFolder): Promise<void> {
	if (!panel) {
		return;
	}
	const uri = vscode.Uri.joinPath(folder.uri, 'bom.json');
	let rows: BomRow[] = [];
	try {
		const bytes = await vscode.workspace.fs.readFile(uri);
		const loaded: unknown = JSON.parse(Buffer.from(bytes).toString('utf8'));
		if (Array.isArray(loaded)) {
			rows = loaded.filter((row): row is BomRow => !!row && typeof row === 'object');
		}
	} catch {
		rows = [];
	}
	await panel.webview.postMessage({ type: 'bom', rows });
}

function html(webview: vscode.Webview, scriptUri: vscode.Uri): string {
	const csp = webview.cspSource;
	const src = webview.asWebviewUri(scriptUri);
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${csp} 'unsafe-inline'; script-src ${csp};">
	<style>
		body { margin: 0; padding: 16px; background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); }
		table { border-collapse: collapse; width: 100%; }
		th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--vscode-panel-border); }
		th { color: var(--vscode-descriptionForeground); font-weight: 600; }
		#empty { color: var(--vscode-descriptionForeground); }
	</style>
</head>
<body>
	<p id="empty"></p>
	<table>
		<thead>
			<tr><th>Part</th><th>Description</th><th>Qty</th><th>Vendor</th></tr>
		</thead>
		<tbody id="rows"></tbody>
	</table>
	<script src="${src}"></script>
</body>
</html>`;
}
