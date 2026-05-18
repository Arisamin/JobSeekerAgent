using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;

namespace WpfSshCommandTool
{
    public partial class MainWindow : Window
    {
        private class SshCommand
        {
            public string Name { get; set; } = string.Empty;
            public string Command { get; set; } = string.Empty;
            public List<(string Label, string Default)> Parameters { get; set; } = new();
        }
        private List<SshCommand> _commands = new();

        public MainWindow()
        {
            try
            {
                InitializeComponent();
                LoadCommands();
                if (_commands.Count == 0)
                {
                    MainPanel.Children.Add(new TextBlock { Text = "No commands found in SSH Commands file.", Foreground = System.Windows.Media.Brushes.Red, FontSize = 16 });
                }
                else
                {
                    BuildUi();
                }
            }
            catch (Exception ex)
            {
                MainPanel.Children.Add(new TextBlock { Text = $"Startup error: {ex.Message}", Foreground = System.Windows.Media.Brushes.Red, FontSize = 16 });
                MessageBox.Show($"Fatal error: {ex.Message}", "Fatal Error", MessageBoxButton.OK, MessageBoxImage.Error);
                Application.Current.Shutdown();
            }
        }

        private void LoadCommands()
        {
            // Path to SSH Commands file (absolute path)
            string filePath = @"C:\MyData\Git\AI Projects\Job Seeker Agent\SSH Commands";
            if (!File.Exists(filePath))
            {
                throw new FileNotFoundException($"SSH Commands file not found: {filePath}");
            }
            var lines = File.ReadAllLines(filePath);
            SshCommand? current = null;
            foreach (var line in lines)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                if (line.TrimEnd().EndsWith(":"))
                {
                    if (current != null) _commands.Add(current);
                    current = new SshCommand { Name = line.Trim().TrimEnd(':') };
                }
                else if (current != null && !line.TrimStart().StartsWith("#"))
                {
                    // Try to extract parameters like $targetPid = 130122
                    var paramMatch = Regex.Match(line, @"\$(\w+) *= *([^\s]+)");
                    if (paramMatch.Success)
                    {
                        current.Parameters.Add((paramMatch.Groups[1].Value, paramMatch.Groups[2].Value));
                    }
                    else if (line.Trim().StartsWith("ssh"))
                    {
                        current.Command = line.Trim();
                    }
                }
            }
            if (current != null) _commands.Add(current);
        }

        private void BuildUi()
        {
            foreach (var cmd in _commands)
            {
                var panel = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
                var paramBoxes = new List<TextBox>();
                foreach (var (label, defVal) in cmd.Parameters)
                {
                    panel.Children.Add(new Label { Content = label + ":", VerticalAlignment = VerticalAlignment.Center });
                    var tb = new TextBox { Text = defVal, Width = 80, Margin = new Thickness(0, 0, 10, 0) };
                    panel.Children.Add(tb);
                    paramBoxes.Add(tb);
                }
                var btn = new Button { Content = cmd.Name, MinWidth = 120, Margin = new Thickness(0, 0, 10, 0) };
                btn.Click += (s, e) => CopyCommandToClipboard(cmd, paramBoxes);
                panel.Children.Add(btn);
                MainPanel.Children.Add(panel);
            }
        }

        private void CopyCommandToClipboard(SshCommand cmd, List<TextBox> paramBoxes)
        {
            string command = cmd.Command;
            for (int i = 0; i < cmd.Parameters.Count; i++)
            {
                var (label, _) = cmd.Parameters[i];
                string val = paramBoxes[i].Text;
                command = Regex.Replace(command, $@"\${label}[^\s]*", val);
            }
            try
            {
                Clipboard.SetText(command);
                MessageBox.Show("Command copied to clipboard!", "Copied", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to copy to clipboard: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }
}
