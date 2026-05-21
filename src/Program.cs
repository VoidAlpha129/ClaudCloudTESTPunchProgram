using System.Text.RegularExpressions;
using PdfSharpCore.Pdf;
using PdfSharpCore.Pdf.IO;
using UglyToad.PdfPig;

var app = new PunchPacketBuilder();
return app.Run(args);

internal sealed class PunchPacketBuilder
{
    private static readonly Regex IntRe = new("^\\d+$", RegexOptions.Compiled);
    private static readonly Regex PartRe = new("^[A-Z0-9]{2,}(?:-[A-Z0-9]+)+[A-Z]?$", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public int Run(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine("Usage: dotnet run -- <input-pdf-dir> <output-pdf>");
            return 1;
        }

        var inputDir = new DirectoryInfo(args[0]);
        var outputPath = args[1];
        if (!inputDir.Exists)
        {
            Console.WriteLine($"Input directory not found: {inputDir.FullName}");
            return 2;
        }

        var pdfPaths = inputDir.GetFiles("*.pdf").OrderBy(f => NaturalSortKey(f.Name), StringComparer.OrdinalIgnoreCase).ToList();
        if (pdfPaths.Count == 0)
        {
            Console.WriteLine("No PDF files found.");
            return 3;
        }

        var extracted = ExtractFromStrikerPdfs(pdfPaths);
        Console.WriteLine("Programs:");
        foreach (var kv in extracted.ProgramSheets) Console.WriteLine($"  {kv.Key} = {kv.Value} Sheets");
        Console.WriteLine("Parts:");
        foreach (var kv in extracted.PartTotals) Console.WriteLine($"  {kv.Key} = {kv.Value}");
        Console.WriteLine($"Overall Sheets: {extracted.TotalSheets}");

        MergePdfs(pdfPaths, outputPath);
        Console.WriteLine($"Merged packet written: {outputPath}");

        if (extracted.Warnings.Count > 0)
        {
            Console.WriteLine("Warnings:");
            foreach (var w in extracted.Warnings) Console.WriteLine($" - {w}");
        }

        return 0;
    }

    private static void MergePdfs(IEnumerable<FileInfo> inputs, string outputPath)
    {
        using var outDoc = new PdfDocument();
        foreach (var path in inputs)
        {
            using var inDoc = PdfReader.Open(path.FullName, PdfDocumentOpenMode.Import);
            for (var i = 0; i < inDoc.PageCount; i++) outDoc.AddPage(inDoc.Pages[i]);
        }
        outDoc.Save(outputPath);
    }

    private static ExtractedInfo ExtractFromStrikerPdfs(List<FileInfo> pdfPaths)
    {
        var programSheets = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var partTotals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var totalSheets = 0;
        var warnings = new List<string>();

        foreach (var path in pdfPaths.Where(p => p.Name.StartsWith("0.", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                using var doc = PdfDocument.Open(path.FullName);
                var allLines = doc.GetPages().SelectMany(p => p.Text.Split('\n')).Select(l => l.Trim()).Where(l => l.Length > 0).ToList();

                var program = ExtractProgramNumber(allLines, path.Name);
                var blankQty = ExtractBlankQty(allLines);
                var parts = ExtractParts(allLines);

                if (blankQty > 0) totalSheets += blankQty;
                else warnings.Add($"{path.Name}: No Blank Qty found.");

                if (program is not null) programSheets[program] = programSheets.GetValueOrDefault(program) + blankQty;
                else warnings.Add($"{path.Name}: No Program Number / NC Filename found.");

                foreach (var kv in parts) partTotals[kv.Key] = partTotals.GetValueOrDefault(kv.Key) + kv.Value;
            }
            catch (Exception ex)
            {
                warnings.Add($"{path.Name}: extraction error: {ex.Message}");
            }
        }

        return new ExtractedInfo(programSheets, partTotals, totalSheets, warnings);
    }

    private static string? ExtractProgramNumber(List<string> lines, string fileName)
    {
        var blob = string.Join("\n", lines);
        var nc = Regex.Match(blob, @"NC\s+Filename\s*:\s*([^\r\n]+)", RegexOptions.IgnoreCase);
        if (nc.Success) return CleanProgramNumber(nc.Groups[1].Value);

        for (var i = 0; i < lines.Count; i++)
        {
            if (!Regex.IsMatch(lines[i], @"Program\s+Number\s*:?") || i + 1 >= lines.Count) continue;
            var joined = string.Join("", lines.Skip(i + 1).Take(5));
            var m = Regex.Match(joined, @"\d{3,}-[A-Za-z0-9(),-]+-\d{1,2}-\d{1,2}");
            if (m.Success) return CleanProgramNumber(m.Value);
        }

        var stem = Path.GetFileNameWithoutExtension(fileName).Replace("-NC", "", StringComparison.OrdinalIgnoreCase).Trim();
        return Regex.IsMatch(stem, @"\d{3,}-.+?-\d{1,2}-\d{1,2}$") ? CleanProgramNumber(stem) : null;
    }

    private static int ExtractBlankQty(List<string> lines)
    {
        var start = lines.FindIndex(l => l.StartsWith("Blank Qty", StringComparison.OrdinalIgnoreCase));
        if (start < 0) return 0;
        var end = lines.FindIndex(start + 1, l => l.StartsWith("Hole", StringComparison.OrdinalIgnoreCase));
        if (end < 0) end = lines.Count;
        var values = lines.Skip(start + 1).Take(end - start - 1)
            .Select(t => t.Replace(",", ""))
            .Where(t => IntRe.IsMatch(t))
            .Select(int.Parse)
            .ToList();
        return values.Count == 0 ? 0 : values[^1];
    }

    private static Dictionary<string, int> ExtractParts(List<string> lines)
    {
        var totals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < lines.Count; i++)
        {
            if (!PartRe.IsMatch(lines[i])) continue;
            var ints = new List<int>();
            for (var j = i + 1; j < Math.Min(lines.Count, i + 8); j++)
            {
                var t = lines[j].Replace(",", "");
                if (IntRe.IsMatch(t)) ints.Add(int.Parse(t));
            }
            if (ints.Count >= 2) totals[lines[i]] = totals.GetValueOrDefault(lines[i]) + ints[1];
            else if (ints.Count == 1) totals[lines[i]] = totals.GetValueOrDefault(lines[i]) + ints[0];
        }
        return totals;
    }

    private static string CleanProgramNumber(string value)
    {
        var p = Regex.Replace(value.Trim(), @"\s+", " ").TrimEnd('.', '-', '_', ' ');
        return p.EndsWith(".dat", StringComparison.OrdinalIgnoreCase) ? p : p + ".dat";
    }

    private static string NaturalSortKey(string name) => Regex.Replace(name.ToLowerInvariant(), "(\\d+)", m => m.Value.PadLeft(12, '0'));
}

internal sealed record ExtractedInfo(Dictionary<string, int> ProgramSheets, Dictionary<string, int> PartTotals, int TotalSheets, List<string> Warnings);
