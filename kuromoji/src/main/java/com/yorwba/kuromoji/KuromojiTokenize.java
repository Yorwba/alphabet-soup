package com.yorwba.kuromoji;

import com.atilika.kuromoji.unidic.kanaaccent.Token;
import com.atilika.kuromoji.unidic.kanaaccent.Tokenizer;
import java.util.List;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.IOException;

public class KuromojiTokenize {
    public static void main(String[] args) {
        Tokenizer tokenizer = new Tokenizer();
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        String line;
        try {
            while(null != (line = reader.readLine())) {
                for (Token token : tokenizer.tokenize(line)) {
                    System.out.println(
                            token.getSurface() + "\t"
                            + token.getPartOfSpeechLevel1() + ","
                            + token.getPartOfSpeechLevel2() + ","
                            + token.getPartOfSpeechLevel3() + ","
                            + token.getPartOfSpeechLevel4() + ","
                            + token.getConjugationType() + ","
                            + token.getConjugationForm() + ","
                            + token.getLemma() + ","
                            + getAccentedPronunciation(token)
                    );
                }
                System.out.println("EOS");
            }
        } catch(IOException e) { }
    }

    private static String getAccentedPronunciation(Token token) {
        String accentType = token.getAccentType();
        String unaccented = token.getPronunciation();
        if(accentType.equals("*")) {
            return unaccented;
        }
        int comma = accentType.indexOf(",");
        if(comma != -1) {
            accentType = accentType.substring(0, comma);
        }
        int accentedMora = Integer.parseInt(accentType);
        if(accentedMora == 0) {
            return unaccented;
        }
        if(accentedMora > unaccented.length()) {
            return unaccented;
        }
        return unaccented.substring(0, accentedMora)
            + "↘" + unaccented.substring(accentedMora, unaccented.length());
    }
}
