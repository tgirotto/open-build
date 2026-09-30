/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as path from 'path';
import * as vscode from 'vscode';

const stlPreviewViewType = 'openBuild.stlPreview';

let panel: vscode.WebviewPanel | undefined;

export function registerModelView(context: vscode.ExtensionContext): vscode.Disposable {
	const provider = new StlPreviewProvider(context);
	return vscode.Disposable.from(
		vscode.commands.registerCommand('openBuild.showModel', () => openModel(context)),
		vscode.window.registerCustomEditorProvider(stlPreviewViewType, provider, {
			supportsMultipleEditorsPerDocument: true,
			webviewOptions: { retainContextWhenHidden: true },
		}),
	);
}

class StlPreviewProvider implements vscode.CustomReadonlyEditorProvider {
	constructor(private readonly context: vscode.ExtensionContext) { }

	async openCustomDocument(uri: vscode.Uri): Promise<vscode.CustomDocument> {
		return { uri, dispose() { } };
	}

	async resolveCustomEditor(document: vscode.CustomDocument, webviewPanel: vscode.WebviewPanel): Promise<void> {
		const directory = vscode.Uri.file(path.dirname(document.uri.fsPath));
		webviewPanel.webview.options = {
			enableScripts: true,
			localResourceRoots: [this.context.extensionUri, directory],
		};
		const refresh = () => { void renderWebview(this.context, webviewPanel.webview, document.uri); };
		const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(directory, path.basename(document.uri.fsPath)));
		watcher.onDidChange(refresh);
		watcher.onDidCreate(refresh);
		webviewPanel.onDidDispose(() => watcher.dispose());
		await refresh();
	}
}

async function openModel(context: vscode.ExtensionContext): Promise<void> {
	const folder = vscode.workspace.workspaceFolders?.[0];
	if (!folder) {
		void vscode.window.showErrorMessage(vscode.l10n.t("Open a folder before showing the model."));
		return;
	}

	if (panel) {
		panel.reveal(vscode.ViewColumn.Beside);
		await render(context, folder);
		return;
	}

	const created = vscode.window.createWebviewPanel(
		'openBuild.model',
		vscode.l10n.t("Model"),
		vscode.ViewColumn.Beside,
		{
			enableScripts: true,
			localResourceRoots: [context.extensionUri, folder.uri],
			retainContextWhenHidden: true,
		},
	);
	panel = created;
	const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, 'geometry/part.stl'));
	const refresh = () => { void render(context, folder); };
	created.onDidDispose(() => {
		watcher.dispose();
		panel = undefined;
	});
	watcher.onDidCreate(refresh);
	watcher.onDidChange(refresh);
	context.subscriptions.push(created);
	await render(context, folder);
}

async function render(context: vscode.ExtensionContext, folder: vscode.WorkspaceFolder): Promise<void> {
	if (!panel) {
		return;
	}
	const stl = vscode.Uri.joinPath(folder.uri, 'geometry', 'part.stl');
	let stlUri: vscode.Uri | undefined;
	try {
		await vscode.workspace.fs.stat(stl);
		stlUri = stl;
	} catch {
		stlUri = undefined;
	}
	await renderWebview(context, panel.webview, stlUri);
}

function renderWebview(context: vscode.ExtensionContext, webview: vscode.Webview, stlUri: vscode.Uri | undefined): void {
	const threeUri = vscode.Uri.joinPath(context.extensionUri, 'node_modules', 'three', 'build', 'three.module.min.js');
	const scriptUri = vscode.Uri.joinPath(context.extensionUri, 'media', 'model.js');
	const stamp = Date.now();
	const mesh = stlUri ? `${webview.asWebviewUri(stlUri)}?t=${stamp}` : '';
	webview.html = html(webview, webview.asWebviewUri(threeUri), webview.asWebviewUri(scriptUri), mesh);
}

function html(webview: vscode.Webview, threeUri: vscode.Uri, scriptUri: vscode.Uri, mesh: string): string {
	const csp = webview.cspSource;
	const empty = mesh.length === 0;
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${csp} 'unsafe-inline'; script-src ${csp}; connect-src ${csp};">
	<style>
		html, body { margin: 0; height: 100%; background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); font-family: var(--vscode-font-family); }
		#empty { display: ${empty ? 'flex' : 'none'}; height: 100%; align-items: center; justify-content: center; }
		canvas { display: ${empty ? 'none' : 'block'}; width: 100%; height: 100%; }
	</style>
</head>
<body>
	<div id="viewer" data-stl="${mesh}" data-three="${threeUri}" hidden></div>
	<div id="empty">${vscode.l10n.t("Compile geometry to show the model.")}</div>
	<script type="module" src="${scriptUri}"></script>
</body>
</html>`;
}
