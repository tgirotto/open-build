/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { registerBomView } from './bomView';
import { registerModelView } from './modelView';
import { createEngineeringProject } from './scaffold';

const providerId = 'open-build';

export function activate(context: vscode.ExtensionContext): void {
	const didChange = new vscode.EventEmitter<void>();
	context.subscriptions.push(didChange);
	context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => didChange.fire()));
	context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
		if (event.affectsConfiguration('openBuild.pythonPath')) {
			didChange.fire();
		}
	}));
	context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider(providerId, {
		onDidChangeMcpServerDefinitions: didChange.event,
		provideMcpServerDefinitions: () => provideServer(context),
	}));
	context.subscriptions.push(vscode.commands.registerCommand('openBuild.newProject', () => createEngineeringProject(context)));
	context.subscriptions.push(registerModelView(context));
	context.subscriptions.push(registerBomView(context));
}

function provideServer(context: vscode.ExtensionContext): vscode.McpStdioServerDefinition[] {
	const folder = vscode.workspace.workspaceFolders?.[0];
	if (!folder) {
		return [];
	}
	const definition = new vscode.McpStdioServerDefinition(
		vscode.l10n.t("Open Build"),
		pythonCommand(context),
		['-m', 'openbuild_tools'],
		{
			PYTHONPATH: vscode.Uri.joinPath(context.extensionUri, 'python').fsPath,
			OPENBUILD_WORKSPACE: folder.uri.fsPath,
		},
	);
	definition.cwd = folder.uri;
	return [definition];
}

function pythonCommand(context: vscode.ExtensionContext): string {
	const configured = vscode.workspace.getConfiguration('openBuild').get<string>('pythonPath', 'python3').trim();
	if (configured.length > 0 && configured !== 'python3') {
		return configured;
	}
	const bundled = path.join(context.extensionUri.fsPath, 'python', '.venv', process.platform === 'win32' ? path.join('Scripts', 'python.exe') : path.join('bin', 'python'));
	if (fs.existsSync(bundled)) {
		return bundled;
	}
	return configured.length > 0 ? configured : 'python3';
}
